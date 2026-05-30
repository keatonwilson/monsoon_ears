"""GET /aprs"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from db.queries import recent_aprs

router = APIRouter(prefix="/aprs", tags=["aprs"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "callsign": row.callsign,
        "lat": row.lat,
        "lon": row.lon,
        "symbol": row.symbol,
        "comment": row.comment,
        "temp_f": row.temp_f,
        "rainfall_in": row.rainfall_in,
        "wind_mph": row.wind_mph,
        "source": row.source,
    }


@router.get("")
def list_aprs(
    minutes: int = Query(30, ge=1, le=60 * 24 * 7),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    rows = recent_aprs(minutes=minutes)[:limit]
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}
