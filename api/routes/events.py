"""GET /events, GET /events/{id}"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from config.frequencies import talkgroup_label
from db.queries import event_by_id, events_since, recent_transcriptions

router = APIRouter(prefix="/events", tags=["events"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "frequency_mhz": row.frequency_mhz,
        "raw_text": row.raw_text,
        "corrected_text": row.corrected_text,
        "duration_sec": row.duration_sec,
        "source": row.source,
        "talkgroup_id": row.talkgroup_id,
        "talkgroup_label": talkgroup_label(row.talkgroup_id),
        "transmission_type": row.transmission_type,
        "confidence": row.confidence,
        "language": row.language,
        "locations": row.locations,
        "incident_type": row.incident_type,
        "callsigns": row.callsigns,
        "units": row.units,
        "status_codes": row.status_codes,
        "severity": row.severity,
        "lat": row.lat,
        "lon": row.lon,
        "wash_name": row.wash_name,
        "road_closure": row.road_closure,
    }


@router.get("")
def list_events(
    limit: int = Query(50, ge=1, le=500),
    source: Optional[str] = Query(None, description="analog | p25"),
    type: Optional[str] = Query(None, description="transmission_type filter"),
    since_minutes: Optional[int] = Query(None, ge=1, le=60 * 24 * 30),
) -> dict[str, Any]:
    if since_minutes is not None or type is not None:
        rows = events_since(
            since_minutes=since_minutes or 60 * 24,
            limit=limit,
            source=source,
            transmission_type=type,
        )
    else:
        rows = recent_transcriptions(limit=limit, source=source)
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}


@router.get("/{event_id}")
def get_event(event_id: int) -> dict[str, Any]:
    row = event_by_id(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"event {event_id} not found")
    return _serialize(row)
