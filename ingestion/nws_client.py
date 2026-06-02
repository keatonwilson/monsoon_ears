"""NWS active-alerts client — api.weather.gov watches/warnings/advisories.

The keystone weather source: an official Flash Flood Warning for the Tucson
point is the strongest flood signal we can get, and it feeds both the monsoon
digest and (later) the Band Manager. We query the public, documented
`/alerts/active` endpoint by point — NWS resolves the containing zones and
returns only the alerts active there, so client-side filtering is minimal.

    https://api.weather.gov/alerts/active?point=32.2,-110.97

api.weather.gov requires a descriptive User-Agent with contact info (it rejects
anonymous/placeholder agents), and prefers `Accept: application/geo+json`.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from models.schemas import WeatherAlert

logger = logging.getLogger(__name__)

ALERTS_URL = "https://api.weather.gov/alerts/active"


def nws_enabled() -> bool:
    return os.getenv("NWS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _point() -> str:
    return os.getenv("NWS_POINT", "32.2,-110.97").strip()


def _user_agent() -> str:
    # NWS 403s contact-less agents; require a real identifier (same policy as
    # our Nominatim UA).
    return os.getenv(
        "NWS_USER_AGENT",
        "monsoon-ears/1.0 (+https://github.com/keatonwilson/monsoon_ears)",
    )


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_nws_alerts(payload: dict, fetched_at: Optional[datetime] = None) -> list[WeatherAlert]:
    """Parse a GeoJSON FeatureCollection from /alerts/active into WeatherAlerts.
    Pure. Skips Test-status and Cancel messages (not actionable)."""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    out: list[WeatherAlert] = []
    for feature in payload.get("features") or []:
        p = feature.get("properties") or {}
        alert_id = p.get("id")
        event = p.get("event")
        if not alert_id or not event:
            continue
        if (p.get("status") or "").lower() == "test":
            continue
        if (p.get("messageType") or "").lower() == "cancel":
            continue
        out.append(WeatherAlert(
            alert_id=alert_id,
            event=event,
            severity=p.get("severity"),
            certainty=p.get("certainty"),
            urgency=p.get("urgency"),
            headline=p.get("headline"),
            description=p.get("description"),
            area_desc=p.get("areaDesc"),
            status=p.get("status"),
            message_type=p.get("messageType"),
            onset=_parse_dt(p.get("onset") or p.get("effective")),
            expires=_parse_dt(p.get("expires") or p.get("ends")),
            sent=_parse_dt(p.get("sent")),
            fetched_at=fetched_at,
        ))
    return out


def fetch_nws_alerts(point: Optional[str] = None, timeout: int = 20) -> list[WeatherAlert]:
    """Fetch + parse active NWS alerts for the configured Tucson point."""
    import requests

    resp = requests.get(
        ALERTS_URL,
        params={"point": point or _point()},
        headers={"User-Agent": _user_agent(), "Accept": "application/geo+json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    alerts = parse_nws_alerts(resp.json())
    logger.info("NWS: %d active alert(s) for point %s", len(alerts), point or _point())
    return alerts
