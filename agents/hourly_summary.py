"""Hourly all-events summary agent.

Where the thread summarizer zooms in on a single conversation, this zooms out:
once an hour it rolls up *everything* that crossed the wire — voice events by
type, the thread narratives, APRS weather, stream gauges, and active NWS alerts
— into one wide-angle digest the dashboard shows on a "Last hour" tab.

The countable stats (event totals, per-type counts, peak severity, gauge/weather
notes) are computed deterministically in code; only the prose narrative and the
"top incidents" shortlist come from Haiku. A quiet hour (no non-noise voice
events) is persisted as an empty rollup *without* an LLM call — same cost
discipline as the monsoon digest.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field

from config.locale import PLACE_NAME
from db.queries import (
    active_weather_alerts,
    events_since,
    insert_hourly_summary,
    recent_aprs,
    recent_gauges,
    recent_threads,
)

logger = logging.getLogger(__name__)

# Severity ranking for picking the hour's peak.
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


class HourlySummaryResponse(BaseModel):
    """The LLM-authored portion of the rollup."""
    summary: str = Field(
        ...,
        description="A 2-4 sentence plain-English digest of the last hour across "
                    "all sources — what kinds of activity, anything notable, and "
                    "the flood/weather posture. No bullet lists.",
    )
    top_incidents: list[str] = Field(
        default_factory=list,
        description="Up to 5 short one-line descriptions of the hour's most "
                    "notable incidents (e.g. 'Structure fire on Speedway'). "
                    "Empty if nothing stood out.",
    )


def _is_real_event(row) -> bool:
    """Drop unclassified / UNKNOWN voice events — they're noise for a rollup."""
    ttype = (row.transmission_type or "unknown").lower()
    return ttype not in ("", "unknown")


def _by_type(events) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        t = (e.transmission_type or "unknown").lower()
        counts[t] = counts.get(t, 0) + 1
    return counts


def _severity_max(events) -> Optional[str]:
    best = 0
    best_label: Optional[str] = None
    for e in events:
        rank = _SEVERITY_RANK.get((e.severity or "").lower(), 0)
        if rank > best:
            best, best_label = rank, (e.severity or "").lower()
    return best_label


def _gauge_note(gauge_rows) -> Optional[str]:
    """A one-line peak-discharge note, or None when gauges are flat/absent."""
    peak = None
    for r in gauge_rows:
        if r.discharge_cfs is not None and (peak is None or r.discharge_cfs > peak.discharge_cfs):
            peak = r
    if peak is None:
        return None
    where = peak.site_name or peak.site_id
    return f"peak discharge {peak.discharge_cfs:.0f} cfs at {where}"


def _weather_note(weather_rows) -> Optional[str]:
    if not weather_rows:
        return None
    events = ", ".join(sorted({w.event for w in weather_rows if w.event}))
    return f"active NWS: {events}" if events else None


def _build_prompt(
    *, window_min: int, by_type: dict[str, int], threads, aprs_rows,
    gauge_note: Optional[str], weather_note: Optional[str],
) -> str:
    type_line = ", ".join(f"{t}={n}" for t, n in sorted(by_type.items())) or "(none)"
    thread_lines = "\n".join(
        f"  - {(t.summary or '').strip()[:200]}"
        for t in threads if t.summary and not getattr(t, "is_noise", False)
    ) or "  (no thread summaries)"
    aprs_line = (
        f"{len(aprs_rows)} APRS weather packet(s); "
        + (", ".join(
            f"{a.callsign} rain={a.rainfall_in:.2f}in"
            for a in aprs_rows if (a.rainfall_in or 0) > 0
        ) or "no rainfall reported")
    )
    return (
        f"Summarize the last {window_min} minutes of {PLACE_NAME} public-safety and "
        "weather monitoring into a wide-angle digest.\n\n"
        f"Voice events by type: {type_line}\n"
        f"Gauges: {gauge_note or 'flat / none'}\n"
        f"Weather: {weather_note or 'no active alerts'}\n"
        f"APRS: {aprs_line}\n\n"
        "Conversation summaries this hour:\n"
        f"{thread_lines}\n\n"
        "Write a 2-4 sentence digest of what the hour looked like overall, and "
        "list up to 5 top_incidents (one short line each). Don't invent detail "
        "not present above; a quiet, routine hour is a fine and common answer."
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def hourly_summary(
    window_min: Optional[int] = None,
    client=None,
    model: Optional[str] = None,
) -> int:
    """Build and persist one hourly rollup. Returns the new row id.

    Skips the LLM call (cheap "quiet hour" row) when no real voice events
    occurred in the window — mirrors the monsoon-digest cost gate.
    """
    window_min = window_min or int(os.getenv("HOURLY_INTERVAL_MIN", 60))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_min)

    all_events = events_since(since_minutes=window_min)
    events = [e for e in all_events if _is_real_event(e)]
    threads = recent_threads(since_minutes=window_min, limit=100)
    aprs_rows = recent_aprs(minutes=window_min)
    gauge_rows = recent_gauges(minutes=window_min)
    weather_rows = active_weather_alerts()

    by_type = _by_type(events)
    gauge_note = _gauge_note(gauge_rows)
    weather_note = _weather_note(weather_rows)
    severity_max = _severity_max(events)

    if not events:
        logger.info("hourly_summary: quiet hour (no real voice events), skipping LLM")
        return insert_hourly_summary(
            window_start=window_start, window_end=now,
            summary="Quiet hour — no significant radio activity.",
            event_count=0, by_type=None, top_incidents=None,
            severity_max=None, gauge_note=gauge_note, weather_note=weather_note,
        )

    client = client if client is not None else _get_client()
    model_name = model or os.getenv("HOURLY_MODEL", "claude-haiku-4-5-20251001")
    response: HourlySummaryResponse = client.messages.create(
        model=model_name,
        max_tokens=512,
        messages=[{"role": "user", "content": _build_prompt(
            window_min=window_min, by_type=by_type, threads=threads,
            aprs_rows=aprs_rows, gauge_note=gauge_note, weather_note=weather_note,
        )}],
        response_model=HourlySummaryResponse,
    )
    row_id = insert_hourly_summary(
        window_start=window_start, window_end=now,
        summary=response.summary,
        event_count=len(events),
        by_type=by_type,
        top_incidents=response.top_incidents or None,
        severity_max=severity_max,
        gauge_note=gauge_note,
        weather_note=weather_note,
    )
    logger.info("hourly_summary: %d events, severity_max=%s -> row %d",
                len(events), severity_max, row_id)
    return row_id
