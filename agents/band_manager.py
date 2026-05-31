"""Band Manager — decides how the single dongle's time is split each cycle.

The SDR supervisor (ingestion/sdr_supervisor.py) owns the one RTL-SDR and can run
only one RF "leg" at a time: the analog FM scanner or op25/P25. The Band Manager
turns "current conditions" into a concrete **dwell plan** — an ordered list of
(leg, seconds) summing to the cycle length.

Two layers, by design:

* **Rules baseline** (`_baseline_plan`): a deterministic, P25-primary split read
  straight from env weights. Pure, always works, no LLM. This alone resolves the
  contention that previously had two services fighting for the device.
* **Agentic override** (`_agentic_adjust`, gated by ``BAND_MANAGER_AGENT``): a
  cheap LLM call reads the situational snapshot (agents/context.py) and re-weights
  the split — camp on P25 when flooding looks active/likely, widen analog when
  quiet. Output is clamped to a safe band and any failure falls back to baseline,
  so the agent can only ever *tune* the rota, never break it.

P25/PCWIN carries Tucson Fire, Rural Metro, AMR and the Pima County EOC — the
richest flood-response source — hence the P25-primary default. Analog adds NW
Fire, the ham repeater, periodic NOAA Weather Radio visits, and Rural Metro
fireground.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from agents.context import Situation, situational_snapshot

logger = logging.getLogger(__name__)

LEG_P25 = "p25"
LEG_ANALOG = "analog"

# Never let a clamped/agent weight starve a leg entirely (a leg can still be
# fully disabled via SDR_ENABLE_*; this only bounds the *split* between enabled
# legs).
_MIN_WEIGHT = 0.05


# --- plan types --------------------------------------------------------------


@dataclass(frozen=True)
class DwellSegment:
    leg: str
    seconds: float


@dataclass(frozen=True)
class DwellPlan:
    segments: list[DwellSegment]
    rationale: str
    source: str  # "baseline" | "agent" | "single-leg"
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.segments)


# --- env helpers -------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def enabled_legs() -> list[str]:
    """Which RF legs the supervisor may run, from SDR_ENABLE_* env flags.

    P25 defaults OFF — the op25 UDP audio backend isn't wired yet (see
    deploy/op25_setup.md §4), so until then the supervisor runs analog only and
    the scheduler degrades to a single-leg plan.
    """
    legs = []
    if _env_bool("SDR_ENABLE_ANALOG", True):
        legs.append(LEG_ANALOG)
    if _env_bool("SDR_ENABLE_P25", False):
        legs.append(LEG_P25)
    return legs


def baseline_weights() -> dict[str, float]:
    """Default P25-primary weights, overridable per-leg via env.

    SDR_DEFAULT_POSTURE seeds the defaults (p25 / balanced / analog); explicit
    SDR_P25_WEIGHT / SDR_ANALOG_WEIGHT win if set.
    """
    posture = os.getenv("SDR_DEFAULT_POSTURE", "p25").strip().lower()
    if posture == "balanced":
        p25_default, analog_default = 0.5, 0.5
    elif posture == "analog":
        p25_default, analog_default = 0.3, 0.7
    else:  # "p25" (default)
        p25_default, analog_default = 0.7, 0.3
    return {
        LEG_P25: _env_float("SDR_P25_WEIGHT", p25_default),
        LEG_ANALOG: _env_float("SDR_ANALOG_WEIGHT", analog_default),
    }


# --- allocation (pure) -------------------------------------------------------


def _allocate(weights: dict[str, float], cycle_sec: float, floor_sec: float) -> dict[str, float]:
    """Split ``cycle_sec`` across legs by weight, guaranteeing each ≥ floor_sec
    and the total == cycle_sec exactly."""
    legs = list(weights)
    n = len(legs)
    if n == 0:
        return {}
    if n == 1:
        return {legs[0]: cycle_sec}
    total_floor = floor_sec * n
    if total_floor >= cycle_sec:  # cycle too short to honour floors — split even
        return {leg: cycle_sec / n for leg in legs}
    free = cycle_sec - total_floor
    wsum = sum(weights.values()) or 1.0
    return {leg: floor_sec + free * (weights[leg] / wsum) for leg in legs}


def _ordered_segments(alloc: dict[str, float]) -> list[DwellSegment]:
    """P25-primary ordering: longest dwell first; P25 wins ties so it leads."""
    def key(leg: str) -> tuple[float, int]:
        return (alloc[leg], 1 if leg == LEG_P25 else 0)

    return [DwellSegment(leg, alloc[leg]) for leg in sorted(alloc, key=key, reverse=True)]


def _normalise_clamped(weights: dict[str, float]) -> dict[str, float]:
    """Clamp each weight to ≥ _MIN_WEIGHT and renormalise to sum 1."""
    clamped = {leg: max(_MIN_WEIGHT, float(w)) for leg, w in weights.items()}
    total = sum(clamped.values()) or 1.0
    return {leg: w / total for leg, w in clamped.items()}


# --- agentic layer -----------------------------------------------------------


class _BandPlanResponse(BaseModel):
    """Structured LLM output: relative weights + why."""

    p25_weight: float = Field(ge=0.0, le=1.0)
    analog_weight: float = Field(ge=0.0, le=1.0)
    rationale: str


_AGENT_PROMPT = """You allocate a single radio receiver's listening time between two legs:

- "p25": the PCWIN P25 trunked system — Tucson Fire, Rural Metro, AMR, and the
  Pima County EOC. The richest source of flood/fire/EMS response traffic.
- "analog": a scanner over analog FM channels — NW Fire, a ham repeater, periodic
  NOAA Weather Radio forecast visits, and Rural Metro fireground.

Only one leg can be tuned at a time, so you split the next cycle between them.

Current conditions:
{situation}

Baseline split (P25-primary): p25={p25_base:.2f}, analog={analog_base:.2f}.

Favor p25 when flooding looks active or imminent (recent flood/fire/EMS traffic,
rising stream discharge or gage height, heavy APRS rainfall, monsoon season).
Widen analog when things are quiet (to sweep more channels and catch NOAA
forecasts). Return weights in [0,1] that roughly sum to 1, plus a one-line
rationale."""


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def _agentic_adjust(
    situation: Situation,
    base_weights: dict[str, float],
    client=None,
    model: str | None = None,
) -> tuple[dict[str, float], str] | None:
    """Ask the LLM to re-weight the split. Returns (weights, rationale) or None
    on any failure (caller falls back to baseline)."""
    try:
        client = client if client is not None else _get_client()
        model_name = model or os.getenv("BAND_MANAGER_MODEL", "claude-haiku-4-5-20251001")
        prompt = _AGENT_PROMPT.format(
            situation=situation.summary_line(),
            p25_base=base_weights.get(LEG_P25, 0.0),
            analog_base=base_weights.get(LEG_ANALOG, 0.0),
        )
        resp: _BandPlanResponse = client.messages.create(
            model=model_name,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
            response_model=_BandPlanResponse,
        )
        weights = _normalise_clamped({
            LEG_P25: resp.p25_weight,
            LEG_ANALOG: resp.analog_weight,
        })
        return weights, resp.rationale.strip()
    except Exception as exc:  # noqa: BLE001 — scheduling must never crash on the agent
        logger.warning("band_manager: agent adjust failed, using baseline: %s", exc)
        return None


# --- public entry point ------------------------------------------------------


def plan_dwell(
    cycle_sec: float | None = None,
    legs: list[str] | None = None,
    floor_sec: float | None = None,
    snapshot: Situation | None = None,
    client=None,
    model: str | None = None,
) -> DwellPlan:
    """Produce the dwell plan for the next cycle.

    Deterministic by default; consults the LLM only when BAND_MANAGER_AGENT is on
    AND more than one leg is enabled. Any agent failure degrades to baseline.
    """
    cycle_sec = cycle_sec if cycle_sec is not None else _env_float("SDR_CYCLE_MIN", 10.0) * 60.0
    floor_sec = floor_sec if floor_sec is not None else _env_float("SDR_LEG_FLOOR_SEC", 60.0)
    legs = legs if legs is not None else enabled_legs()

    if not legs:
        return DwellPlan(segments=[], rationale="no RF legs enabled", source="baseline")

    base = {leg: w for leg, w in baseline_weights().items() if leg in legs}

    # One leg → it gets the whole cycle; no point asking the agent.
    if len(legs) == 1:
        leg = legs[0]
        return DwellPlan(
            segments=[DwellSegment(leg, cycle_sec)],
            rationale=f"only {leg} enabled",
            source="single-leg",
            weights={leg: 1.0},
        )

    weights, rationale, source = base, "P25-primary baseline rota", "baseline"

    if _env_bool("BAND_MANAGER_AGENT", False):
        snap = snapshot if snapshot is not None else situational_snapshot()
        adjusted = _agentic_adjust(snap, base, client=client, model=model)
        if adjusted is not None:
            weights, agent_rationale = adjusted
            rationale, source = agent_rationale, "agent"
            logger.info("band_manager: agent plan %s — %s", weights, rationale)

    alloc = _allocate(weights, cycle_sec, floor_sec)
    return DwellPlan(
        segments=_ordered_segments(alloc),
        rationale=rationale,
        source=source,
        weights=weights,
    )
