"""Alert layer: rule-based push + LLM-based monsoon correlation digest.

Two paths:

* **Rule eval (per event):** if an extracted event is `severity=HIGH` or
  `road_closure=True`, push immediately to Ntfy.sh. Cheap, deterministic,
  fires on every qualifying event.
* **Monsoon digest (every 15 min):** Sonnet reads the last hour of
  fire/EMS/flood-control voice traffic plus the last 30 min of APRS weather
  packets and decides whether they look correlated. If yes, pushes a
  summary. This is the showcase capability.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel

# `looks_like_hallucination` is re-exported here for backwards compatibility —
# it used to live in this module before being shared with the classify stage.
from agents.hallucination import MIN_ALERT_CONFIDENCE, looks_like_hallucination
from db.queries import insert_alert, recent_aprs, recent_flood_events
from models.schemas import AlertDecision, ExtractedEvent, Severity

logger = logging.getLogger(__name__)


# --- Rule-based alert --------------------------------------------------------


def evaluate_alert(extracted: ExtractedEvent) -> AlertDecision:
    """Pure rule: fire if HIGH severity OR an explicit road closure.

    Two suppression guards stop Whisper ghosts from waking the user's phone:
    transcripts that look hallucinated, and HIGH-severity tags riding in on a
    low-confidence classification (the classifier short-circuits obvious ghosts
    to confidence 0.0, so this also catches whatever the pre-gate flagged).
    """
    if looks_like_hallucination(extracted.raw_text):
        return AlertDecision(
            should_alert=False,
            reason="suppressed: low-quality transcript",
        )
    if extracted.severity is Severity.HIGH and extracted.confidence < MIN_ALERT_CONFIDENCE:
        return AlertDecision(
            should_alert=False,
            reason="suppressed: low classifier confidence",
        )
    if extracted.severity is Severity.HIGH:
        return AlertDecision(
            should_alert=True,
            reason="severity=HIGH",
            summary=f"{extracted.transmission_type.value.upper()}: {extracted.raw_text[:160]}",
        )
    if extracted.road_closure is True:
        return AlertDecision(
            should_alert=True,
            reason="road_closure=True",
            summary=f"Road closure reported: {extracted.raw_text[:160]}",
        )
    return AlertDecision(should_alert=False)


# --- Ntfy.sh push ------------------------------------------------------------


def push_ntfy(
    title: str,
    body: str,
    topic: Optional[str] = None,
    base_url: Optional[str] = None,
    requests_module=None,
) -> bool:
    """POST a notification to Ntfy. Returns True on 2xx, False otherwise."""
    topic = topic or os.getenv("NTFY_TOPIC")
    if not topic or topic.endswith("CHANGE-ME"):
        logger.warning("NTFY_TOPIC not configured; skipping push")
        return False
    base = base_url or os.getenv("NTFY_BASE_URL", "https://ntfy.sh")
    url = f"{base.rstrip('/')}/{topic}"
    req = requests_module
    if req is None:
        import requests as req
    try:
        resp = req.post(
            url, data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high"},
            timeout=10,
        )
        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.warning("Ntfy push returned %s: %s", resp.status_code, resp.text[:200])
        return ok
    except Exception as exc:  # noqa: BLE001 — alerting must not crash worker
        logger.warning("Ntfy push failed: %s", exc)
        return False


# --- LLM digest (Sonnet) -----------------------------------------------------


# Verbatim from .claude/plan.md §Phase 03 — the monsoon correlation prompt.
_MONSOON_PROMPT = """You are monitoring Tucson emergency radio and APRS weather stations.

Recent flood-control / fire / EMS radio activity (last {voice_window} min):
{flood_events}

APRS weather station readings near mentioned locations (last {aprs_window} min):
{aprs_weather}

Are these consistent with an active flash flood situation?
Identify washes mentioned, correlate with nearby rainfall data,
assess severity, and flag if road closures appear imminent.
"""


class DigestResponse(BaseModel):
    """Structured digest output — re-uses AlertDecision shape so we can persist later."""
    should_alert: bool
    summary: Optional[str] = None
    reason: Optional[str] = None
    correlation_note: Optional[str] = None
    correlated_event_ids: list[int] = []


def _format_flood_events(rows) -> str:
    if not rows:
        return "(none)"
    lines = []
    for r in rows[:30]:
        text = (r.raw_text or "").strip().replace("\n", " ")
        lines.append(
            f"- id={r.id} {r.timestamp:%H:%M} {r.transmission_type or '?'} "
            f"@ {r.frequency_mhz}MHz: {text[:140]}"
        )
    return "\n".join(lines)


def _format_aprs(rows) -> str:
    if not rows:
        return "(none)"
    lines = []
    for r in rows[:30]:
        bits = []
        if r.temp_f is not None:
            bits.append(f"temp={r.temp_f:.0f}F")
        if r.rainfall_in is not None:
            bits.append(f"rain={r.rainfall_in:.2f}in")
        if r.wind_mph is not None:
            bits.append(f"wind={r.wind_mph:.0f}mph")
        if r.lat is not None and r.lon is not None:
            bits.append(f"@({r.lat:.3f},{r.lon:.3f})")
        lines.append(f"- {r.timestamp:%H:%M} {r.callsign}: " + (", ".join(bits) or "(no wx)"))
    return "\n".join(lines)


_digest_client = None


def _get_digest_client():
    global _digest_client
    if _digest_client is None:
        import anthropic
        import instructor
        _digest_client = instructor.from_anthropic(anthropic.Anthropic())
    return _digest_client


def monsoon_digest(
    voice_window_min: int = 60,
    aprs_window_min: int = 30,
    client=None,
    model: Optional[str] = None,
) -> AlertDecision:
    """Run the Sonnet correlation digest and (optionally) push via Ntfy."""
    voice_rows = recent_flood_events(minutes=voice_window_min)
    aprs_rows = recent_aprs(minutes=aprs_window_min)

    if not voice_rows and not aprs_rows:
        logger.info("monsoon_digest: no recent activity, skipping LLM call")
        return AlertDecision(should_alert=False, reason="no recent activity")

    prompt = _MONSOON_PROMPT.format(
        voice_window=voice_window_min,
        aprs_window=aprs_window_min,
        flood_events=_format_flood_events(voice_rows),
        aprs_weather=_format_aprs(aprs_rows),
    )

    client = client if client is not None else _get_digest_client()
    model_name = model or os.getenv("DIGEST_MODEL", "claude-sonnet-4-6")
    response: DigestResponse = client.messages.create(
        model=model_name,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        response_model=DigestResponse,
    )

    decision = AlertDecision(
        should_alert=response.should_alert,
        reason=response.reason,
        summary=response.summary,
        correlated_event_ids=response.correlated_event_ids,
        correlation_note=response.correlation_note,
    )
    logger.info("monsoon_digest: should_alert=%s reason=%s",
                decision.should_alert, decision.reason)
    if decision.should_alert:
        insert_alert(source="monsoon_digest", decision=decision)
        push_ntfy(
            title="Monsoon correlation",
            body=(decision.summary or "Monsoon-correlated activity detected")
                 + (f"\n\nNote: {decision.correlation_note}" if decision.correlation_note else ""),
        )
    return decision
