"""GET /gauges — recent stream/rain gauge readings (USGS + Pima ALERT)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from config.gauges import site_wash
from db.queries import recent_gauges

router = APIRouter(prefix="/gauges", tags=["gauges"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "source": row.source,
        "site_id": row.site_id,
        "site_name": row.site_name,
        "wash": site_wash(row.site_id),
        "lat": row.lat,
        "lon": row.lon,
        "discharge_cfs": row.discharge_cfs,
        "gage_height_ft": row.gage_height_ft,
        "precip_in": row.precip_in,
    }


@router.get("")
def list_gauges(
    minutes: int = Query(60, ge=1, le=60 * 24 * 7),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    rows = recent_gauges(minutes=minutes)[:limit]
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}
