"""GET /summary — the most recent monsoon-correlation digest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from db.queries import latest_digest_alert

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("")
def get_summary() -> dict[str, Any]:
    """Returns the most recent persisted monsoon-digest alert, or null fields
    if the worker hasn't run a digest yet. Does NOT re-call Sonnet — the
    worker's APScheduler job is the single source of truth for new digests."""
    row = latest_digest_alert()
    if row is None:
        return {
            "available": False,
            "timestamp": None,
            "should_alert": None,
            "reason": None,
            "summary": None,
            "correlation_note": None,
            "correlated_event_ids": [],
        }
    return {
        "available": True,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "should_alert": row.should_alert,
        "reason": row.reason,
        "summary": row.summary,
        "correlation_note": row.correlation_note,
        "correlated_event_ids": row.correlated_event_ids or [],
    }
