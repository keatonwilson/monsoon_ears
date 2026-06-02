"""GET /weather/alerts — active NWS watches/warnings for the Tucson point."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from db.queries import active_weather_alerts

router = APIRouter(prefix="/weather", tags=["weather"])


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "alert_id": row.alert_id,
        "event": row.event,
        "severity": row.severity,
        "certainty": row.certainty,
        "urgency": row.urgency,
        "headline": row.headline,
        "area_desc": row.area_desc,
        "onset": row.onset.isoformat() if row.onset else None,
        "expires": row.expires.isoformat() if row.expires else None,
        "sent": row.sent.isoformat() if row.sent else None,
    }


@router.get("/alerts")
def list_active_alerts() -> dict[str, Any]:
    """Currently-active NWS alerts (not expired), newest first."""
    rows = active_weather_alerts()
    return {"count": len(rows), "results": [_serialize(r) for r in rows]}
