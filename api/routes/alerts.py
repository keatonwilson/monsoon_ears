"""GET /alerts"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from db.queries import recent_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "source": row.source,
        "transcription_id": row.transcription_id,
        "should_alert": row.should_alert,
        "reason": row.reason,
        "summary": row.summary,
        "correlation_note": row.correlation_note,
        "correlated_event_ids": row.correlated_event_ids or [],
    }


@router.get("")
def list_alerts(
    limit: int = Query(50, ge=1, le=500),
    since_minutes: int = Query(60 * 24, ge=1, le=60 * 24 * 30),
    source: Optional[str] = Query(None, description="rule | monsoon_digest"),
) -> dict[str, Any]:
    rows = recent_alerts(limit=limit, since_minutes=since_minutes, source=source)
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}
