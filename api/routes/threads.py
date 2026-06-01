"""GET /threads, GET /threads/{id}, POST /threads/{id}/summarize"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agents.summarize import summarize_thread
from config.frequencies import talkgroup_label
from db.queries import (
    events_for_thread,
    recent_threads,
    thread_by_id,
)

router = APIRouter(prefix="/threads", tags=["threads"])


def _serialize_thread(row, include_events: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "frequency_mhz": row.frequency_mhz,
        "source": row.source,
        "talkgroup_id": row.talkgroup_id,
        "talkgroup_label": talkgroup_label(row.talkgroup_id),
        "start_timestamp": row.start_timestamp.isoformat() if row.start_timestamp else None,
        "end_timestamp": row.end_timestamp.isoformat() if row.end_timestamp else None,
        "event_count": row.event_count,
        "event_ids": row.event_ids or [],
        "summary": row.summary,
        "transmission_type": row.transmission_type,
        "severity": row.severity,
        "locations": row.locations or [],
        "units": row.units or [],
        "incident_type": row.incident_type,
        "summarized_at": row.summarized_at.isoformat() if row.summarized_at else None,
        "closed": row.closed,
    }
    if include_events:
        out["events"] = [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "raw_text": e.raw_text,
                "duration_sec": e.duration_sec,
                "source": e.source,
                "talkgroup_id": e.talkgroup_id,
                "talkgroup_label": talkgroup_label(e.talkgroup_id),
                "transmission_type": e.transmission_type,
                "severity": e.severity,
            }
            for e in events_for_thread(row.id)
        ]
    return out


@router.get("")
def list_threads(
    limit: int = Query(50, ge=1, le=500),
    since_minutes: int = Query(60 * 24, ge=1, le=60 * 24 * 30),
) -> dict[str, Any]:
    rows = recent_threads(limit=limit, since_minutes=since_minutes)
    return {"count": len(rows), "results": [_serialize_thread(r) for r in rows]}


@router.get("/{thread_id}")
def get_thread(thread_id: int) -> dict[str, Any]:
    row = thread_by_id(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"thread {thread_id} not found")
    return _serialize_thread(row, include_events=True)


@router.post("/{thread_id}/summarize")
def force_summarize(thread_id: int) -> dict[str, Any]:
    """Re-run the summary agent on this thread, ignoring `summarized_at`."""
    row = thread_by_id(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"thread {thread_id} not found")
    try:
        summarize_thread(thread_id)
    except Exception as exc:  # noqa: BLE001 — bubble up to client
        raise HTTPException(status_code=502, detail=f"summarizer failed: {exc}")
    updated = thread_by_id(thread_id)
    return _serialize_thread(updated, include_events=True)
