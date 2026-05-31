"""USGS Water Services client — real-time stream/rain gauge readings.

The instantaneous-values (IV) service returns, per site and parameter, a small
time series whose last point is the latest reading. We keep the latest value of
each parameter we care about and merge a site's parameters into one
`GaugeReading`.

    https://waterservices.usgs.gov/nwis/iv/?format=json&sites=...&parameterCd=00060,00065,00045

Parameter codes: 00060 = discharge (cfs), 00065 = gage height (ft),
00045 = precipitation (in). USGS encodes "no data" as the per-variable
`noDataValue` (typically -999999) — those are dropped. Note that a negative
*gage height* and a 0.0 *discharge* are both legitimate readings, so we filter
only on the sentinel, never on sign.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from config.gauges import usgs_site_ids
from models.schemas import GaugeReading

logger = logging.getLogger(__name__)

IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
_PARAM_FIELD = {
    "00060": "discharge_cfs",
    "00065": "gage_height_ft",
    "00045": "precip_in",
}
_SENTINEL = -999999.0


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


def parse_usgs_iv(payload: dict) -> list[GaugeReading]:
    """Parse a USGS IV JSON payload into one GaugeReading per site. Pure."""
    series = (payload.get("value") or {}).get("timeSeries") or []
    by_site: dict[str, dict] = {}

    for ts in series:
        source_info = ts.get("sourceInfo") or {}
        site_codes = source_info.get("siteCode") or [{}]
        site_id = site_codes[0].get("value")
        if not site_id:
            continue

        variable = ts.get("variable") or {}
        param = (variable.get("variableCode") or [{}])[0].get("value")
        field = _PARAM_FIELD.get(param)
        if field is None:
            continue

        no_data = variable.get("noDataValue")
        values = (ts.get("values") or [{}])[0].get("value") or []
        if not values:
            continue
        latest = values[-1]
        try:
            val = float(latest.get("value"))
        except (TypeError, ValueError):
            continue
        if val == _SENTINEL or (no_data is not None and val == no_data):
            continue

        geo = (source_info.get("geoLocation") or {}).get("geogLocation") or {}
        rec = by_site.setdefault(site_id, {
            "site_id": site_id,
            "site_name": source_info.get("siteName"),
            "lat": geo.get("latitude"),
            "lon": geo.get("longitude"),
            "timestamp": None,
            "discharge_cfs": None,
            "gage_height_ft": None,
            "precip_in": None,
        })
        rec[field] = val
        dt = _parse_dt(latest.get("dateTime"))
        if dt and (rec["timestamp"] is None or dt > rec["timestamp"]):
            rec["timestamp"] = dt

    readings: list[GaugeReading] = []
    for rec in by_site.values():
        # Skip sites where every measure came back as no-data.
        if rec["discharge_cfs"] is None and rec["gage_height_ft"] is None and rec["precip_in"] is None:
            continue
        readings.append(GaugeReading(
            source="usgs",
            site_id=rec["site_id"],
            site_name=rec["site_name"],
            lat=rec["lat"],
            lon=rec["lon"],
            timestamp=rec["timestamp"] or datetime.now(timezone.utc),
            discharge_cfs=rec["discharge_cfs"],
            gage_height_ft=rec["gage_height_ft"],
            precip_in=rec["precip_in"],
        ))
    return readings


def fetch_usgs(site_ids: Optional[list[str]] = None, timeout: int = 30) -> list[GaugeReading]:
    """Fetch + parse the latest readings for the configured USGS sites."""
    import requests

    sites = site_ids or usgs_site_ids()
    if not sites:
        return []
    params = {
        "format": "json",
        "sites": ",".join(sites),
        "parameterCd": ",".join(_PARAM_FIELD.keys()),
        "siteStatus": "all",
    }
    resp = requests.get(IV_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    readings = parse_usgs_iv(resp.json())
    logger.info("USGS: parsed %d gauge readings from %d sites", len(readings), len(sites))
    return readings
