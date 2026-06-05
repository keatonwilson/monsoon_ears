"""GET /hourly-summary (latest), GET /hourly-summaries (history)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from db.queries import latest_hourly_summary, recent_hourly_summaries

router = APIRouter(tags=["hourly"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "window_start": row.window_start.isoformat() if row.window_start else None,
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "summary": row.summary,
        "event_count": row.event_count,
        "by_type": row.by_type or {},
        "top_incidents": row.top_incidents or [],
        "severity_max": row.severity_max,
        "gauge_note": row.gauge_note,
        "weather_note": row.weather_note,
    }


@router.get("/hourly-summary")
def get_latest_hourly_summary() -> dict[str, Any]:
    """The most recent hourly rollup, or an empty envelope if none yet."""
    row = latest_hourly_summary()
    return {"summary": _serialize(row) if row else None}


@router.get("/hourly-summaries")
def list_hourly_summaries(
    limit: int = Query(24, ge=1, le=168),
    since_minutes: int = Query(24 * 60, ge=1, le=60 * 24 * 30),
) -> dict[str, Any]:
    rows = recent_hourly_summaries(limit=limit, since_minutes=since_minutes)
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}
