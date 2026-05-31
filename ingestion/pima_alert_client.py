"""Pima County RFCD ALERT rain-gauge client — BEST EFFORT, off by default.

The county ALERT network (alertmap.rfcd.pima.gov) has no documented API: it's a
PHP/Contrail map whose precip table (`pgi.php`) returns an HTML table and 403s a
plain (non-browser) request. So this client:

  * sends browser-like headers,
  * scrapes the precipitation table with stdlib regex (no lxml/bs4 available),
  * and degrades gracefully — any network/parse failure returns [] and logs,
    never raising into the runner.

It is gated by `PIMA_ALERT_ENABLED` (default false). USGS is the stable source;
this just adds the county's denser rain-gauge coverage when it happens to work.
The table gives rainfall over several windows; we keep the 1-hour total as
`precip_in` (comparable to APRS `rain_1h`). No coordinates are published in this
table, so lat/lon are left null.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from models.schemas import GaugeReading

logger = logging.getLogger(__name__)

PRECIP_URL = "https://alertmap.rfcd.pima.gov/gmap/gmap_files/php/Tables/pgi.php"
_MAP_REFERER = "https://alertmap.rfcd.pima.gov/gmap/gmap.html"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)

# Data rows are: <sensor id> <name> <15min> <30min> <1hr> <3hr> <6hr> <12hr> <24hr>
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_ONE_HOUR_COL = 4  # index into the cell list (0=id,1=name,2=15min,3=30min,4=1hr)


def _cell_text(html: str) -> str:
    return _TAG_RE.sub("", html).replace("&nbsp;", " ").strip()


def parse_pima_alert_precip(html: str) -> list[GaugeReading]:
    """Scrape the ALERT precip table into rain-gauge GaugeReadings. Pure.

    Robust to the area-grouping header rows interleaved in the table: a row only
    becomes a reading if its first cell is a numeric sensor id and it has the
    full set of rainfall columns.
    """
    now = datetime.now(timezone.utc)
    readings: list[GaugeReading] = []
    for tr in _TR_RE.findall(html):
        cells = [_cell_text(c) for c in _TD_RE.findall(tr)]
        if len(cells) <= _ONE_HOUR_COL:
            continue
        site_id, name = cells[0], cells[1]
        if not site_id.isdigit():  # skips header / area-label rows
            continue
        try:
            precip_1h = float(cells[_ONE_HOUR_COL])
        except (TypeError, ValueError):
            continue
        readings.append(GaugeReading(
            timestamp=now,
            source="pima_alert",
            site_id=site_id,
            site_name=name or None,
            precip_in=precip_1h,
        ))
    return readings


def fetch_pima_alert(timeout: int = 20) -> list[GaugeReading]:
    """Best-effort fetch of the ALERT precip table. Returns [] on any failure."""
    import requests

    headers = {"User-Agent": _BROWSER_UA, "Referer": _MAP_REFERER}
    try:
        resp = requests.get(PRECIP_URL, headers=headers, timeout=timeout)
        resp.raise_for_status()
        readings = parse_pima_alert_precip(resp.text)
        logger.info("Pima ALERT: parsed %d rain-gauge readings", len(readings))
        return readings
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the runner
        logger.warning("Pima ALERT fetch failed (best-effort, skipping): %s", exc)
        return []


def pima_alert_enabled() -> bool:
    return os.getenv("PIMA_ALERT_ENABLED", "false").lower() == "true"
