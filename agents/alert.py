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
from agents.caching import cached_system
from agents.hallucination import MIN_ALERT_CONFIDENCE, looks_like_hallucination
from config.gauges import site_is_baseflow, site_wash
from db.queries import (
    active_weather_alerts,
    insert_alert,
    recent_aprs,
    recent_flood_events,
    recent_gauges,
)
from models.schemas import AlertDecision, ExtractedEvent, Severity, TransmissionType

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


# The correlation prompt is split into a static instruction block and a
# per-run data block. The static block carries no run-specific bytes so it can
# be served from the prompt cache (cached_system, 1h TTL — the digest runs every
# 15 min, longer than the default 5-min cache life). The volatile event data is
# rendered separately into the user turn. Standing guidance is verbatim from
# .claude/plan.md §Phase 03, expanded with an explicit decision rubric.
_MONSOON_SYSTEM = """You are monitoring Tucson emergency radio, APRS weather \
stations, and official stream/rain gauges for signs of an active flash flood.

Your job each run: decide whether the supplied signals are consistent with an
active or imminent flash flood near Tucson / Pima County, and if so summarize it.

How to weigh the signals:
- An active NWS Flash Flood Warning or Watch is the strongest official signal —
  weigh it heavily.
- Rising stream-gauge discharge or gage height on a named wash is the strongest
  *physical* signal. Correlate it with nearby APRS rainfall and with any washes
  named in the radio traffic.
- Conversely, if NWS shows nothing and rainfall and gauges are flat, be
  skeptical of radio chatter alone — fire/EMS calls happen constantly and are
  not by themselves flood evidence.

Gauges marked [baseflow] carry perennial flow (e.g. a treated-effluent reach),
so steady nonzero discharge there is NORMAL and is NOT by itself a flood signal
— only a clearly rising stage/discharge trend on such a gauge counts. Do not
raise an alert on baseflow alone, especially when rainfall is zero everywhere.

Identify the washes mentioned, correlate rainfall with stream-gauge discharge,
assess severity, and flag if road closures appear imminent. Set should_alert
true only when the evidence genuinely points to flooding; a quiet, well-explained
no-alert verdict is the correct and common outcome. Cite the event ids you
relied on in correlated_event_ids."""

_MONSOON_DATA = """Active NWS watches/warnings/advisories for the Tucson area (official):
{weather_alerts}

Recent flood-control / fire / EMS radio activity (last {voice_window} min):
{flood_events}

APRS weather station readings near mentioned locations (last {aprs_window} min):
{aprs_weather}

Official stream/rain gauge readings — USGS + Pima County ALERT (last {gauge_window} min):
{gauges}

Are these consistent with an active flash flood situation?"""


class DigestResponse(BaseModel):
    """Structured digest output — re-uses AlertDecision shape so we can persist later."""
    should_alert: bool
    summary: Optional[str] = None
    reason: Optional[str] = None
    correlation_note: Optional[str] = None
    correlated_event_ids: list[int] = []


def _format_weather_alerts(rows) -> str:
    if not rows:
        return "(none active)"
    lines = []
    for r in rows[:10]:
        exp = f", expires {r.expires:%H:%M}" if r.expires else ""
        head = (r.headline or r.event or "").strip().replace("\n", " ")
        lines.append(f"- [{r.severity or '?'}] {r.event}{exp}: {head[:160]}")
    return "\n".join(lines)


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


def _format_gauges(rows) -> str:
    if not rows:
        return "(none)"
    lines = []
    for r in rows[:30]:
        bits = []
        if r.discharge_cfs is not None:
            bits.append(f"Q={r.discharge_cfs:.0f}cfs")
        if r.gage_height_ft is not None:
            bits.append(f"stage={r.gage_height_ft:.2f}ft")
        if r.precip_in is not None:
            bits.append(f"precip={r.precip_in:.2f}in")
        wash = site_wash(r.site_id)
        where = f" [{wash}]" if wash else ""
        tag = " [baseflow]" if site_is_baseflow(r.site_id) else ""
        name = (r.site_name or r.site_id)
        lines.append(f"- {r.timestamp:%H:%M} {name}{where}{tag} ({r.source}): " + (", ".join(bits) or "(no data)"))
    return "\n".join(lines)


# --- Digest gating -----------------------------------------------------------
#
# The digest used to call Sonnet on *any* recent activity. But fire/EMS chatter
# is near-constant in a metro area, so that fired the (expensive) Sonnet call
# every 15 min around the clock — ~96 calls/day — even with zero flood risk.
# We now run the LLM only when a genuine flood *signal* is present; routine
# fire/EMS traffic with flat gauges and no rain is logged as a cheap quiet
# verdict without an LLM call. This is mission-safe: flood-control radio
# traffic, rainfall, rising/elevated gauges, and flood-type NWS alerts all still
# trigger a full run.


def _gauge_flood_signal(gauge_rows) -> Optional[str]:
    """Return a human reason if the gauges look flood-relevant, else None.

    Two triggers: a non-baseflow reach running at/above DIGEST_GAUGE_CFS_FLOOR,
    or a clearly rising stage/discharge trend (newest reading >=25% over the
    prior one) on any reach. recent_gauges() returns rows newest-first.
    """
    floor = float(os.getenv("DIGEST_GAUGE_CFS_FLOOR", "50"))
    by_site: dict[str, list] = {}
    for r in gauge_rows:
        by_site.setdefault(r.site_id, []).append(r)
    for site_id, readings in by_site.items():
        newest = readings[0]
        where = site_wash(site_id) or site_id
        if not site_is_baseflow(site_id) and (newest.discharge_cfs or 0.0) >= floor:
            return f"elevated discharge on {where}"
        if len(readings) >= 2:
            prev = readings[1]
            for attr in ("discharge_cfs", "gage_height_ft"):
                new_v = getattr(newest, attr) or 0.0
                old_v = getattr(prev, attr) or 0.0
                if old_v > 0 and new_v >= old_v * 1.25:
                    return f"rising {attr} on {where}"
    return None


def _flood_signal(weather_rows, voice_rows, aprs_rows, gauge_rows) -> Optional[str]:
    """Return a reason string if any signal warrants the LLM correlation, else
    None (meaning: only routine chatter / baseflow — skip the LLM)."""
    for w in weather_rows:
        if "flood" in (w.event or "").lower():
            return f"active NWS alert: {w.event}"
    if any((v.transmission_type or "") == TransmissionType.FLOOD_CONTROL.value for v in voice_rows):
        return "flood-control radio traffic"
    if any((a.rainfall_in or 0.0) > 0 for a in aprs_rows):
        return "APRS rainfall reported"
    return _gauge_flood_signal(gauge_rows)


_digest_client = None


def _get_digest_client():
    global _digest_client
    if _digest_client is None:
        import anthropic
        import instructor
        # The digest's static system block uses a 1h cache TTL (see cached_system),
        # which requires the extended-cache-ttl beta header. Without it the API
        # rejects ttl="1h". The header is harmless when the cache isn't used.
        _digest_client = instructor.from_anthropic(
            anthropic.Anthropic(
                default_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"}
            )
        )
    return _digest_client


def monsoon_digest(
    voice_window_min: int = 60,
    aprs_window_min: int = 30,
    gauge_window_min: int = 60,
    client=None,
    model: Optional[str] = None,
) -> AlertDecision:
    """Run the Sonnet correlation digest and (optionally) push via Ntfy."""
    voice_rows = recent_flood_events(minutes=voice_window_min)
    aprs_rows = recent_aprs(minutes=aprs_window_min)
    gauge_rows = recent_gauges(minutes=gauge_window_min)
    weather_rows = active_weather_alerts()

    signal = _flood_signal(weather_rows, voice_rows, aprs_rows, gauge_rows)

    if not (voice_rows or aprs_rows or gauge_rows or weather_rows):
        logger.info("monsoon_digest: no recent activity, skipping LLM call")
        decision = AlertDecision(should_alert=False, reason="no recent activity")
    elif signal is None:
        # Activity present, but it's routine fire/EMS chatter / baseflow with no
        # flood evidence — skip the Sonnet call and persist a cheap quiet verdict.
        logger.info("monsoon_digest: no flood signal in recent activity, skipping LLM call")
        decision = AlertDecision(should_alert=False, reason="quiet: no flood signal")
    else:
        logger.info("monsoon_digest: flood signal (%s) — running correlation", signal)
        data = _MONSOON_DATA.format(
            voice_window=voice_window_min,
            aprs_window=aprs_window_min,
            gauge_window=gauge_window_min,
            weather_alerts=_format_weather_alerts(weather_rows),
            flood_events=_format_flood_events(voice_rows),
            aprs_weather=_format_aprs(aprs_rows),
            gauges=_format_gauges(gauge_rows),
        )

        client = client if client is not None else _get_digest_client()
        model_name = model or os.getenv("DIGEST_MODEL", "claude-sonnet-4-6")
        # 1024 truncated ~21% of structured outputs in the first soak
        # (instructor IncompleteOutputException) now that the digest also folds in
        # gauges + a fuller event list. 2048 gives the JSON room to close.
        max_tokens = int(os.getenv("DIGEST_MAX_TOKENS", 2048))
        response: DigestResponse = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            # Static standing instructions live in a cached system block (1h TTL
            # so the 15-min cadence still hits); only the volatile data varies.
            system=cached_system(_MONSOON_SYSTEM, ttl="1h"),
            messages=[{"role": "user", "content": data}],
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

    # Persist EVERY verdict (not just alerts) so /summary always reflects the
    # latest run — otherwise a clean "no flood" result leaves the dashboard
    # showing a stale alert. Only PUSH when it's an actual alert.
    insert_alert(source="monsoon_digest", decision=decision)
    if decision.should_alert:
        push_ntfy(
            title="Monsoon correlation",
            body=(decision.summary or "Monsoon-correlated activity detected")
                 + (f"\n\nNote: {decision.correlation_note}" if decision.correlation_note else ""),
        )
    return decision
