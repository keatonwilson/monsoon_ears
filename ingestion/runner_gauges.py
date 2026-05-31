"""Gauge ingestion loop: USGS (+ optional Pima ALERT) -> SQLite.

Polls the configured stream/rain gauges every `GAUGE_POLL_MIN` minutes and
stores new readings as `gauge_readings` rows for the monsoon digest. USGS is
always on; Pima ALERT is best-effort and gated by `PIMA_ALERT_ENABLED`.

In-memory dedup: gauges update on their own cadence (~15 min), so a reading is
only stored when its (site, timestamp) differs from the last one we saw —
avoids piling up identical rows when the poll outpaces the source. For the
high-volume ALERT rain table we keep only gauges currently reporting rain.

Run with:
    uv run python -m ingestion.runner_gauges
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

from db.queries import insert_gauge_reading
from ingestion.pima_alert_client import fetch_pima_alert, pima_alert_enabled
from ingestion.usgs_client import fetch_usgs

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _poll_once(seen: dict[tuple[str, str], str]) -> int:
    """One fetch cycle across enabled sources. Returns rows inserted."""
    readings = list(fetch_usgs())
    if pima_alert_enabled():
        # ALERT is a 100+ gauge rain table; only persist gauges with rain.
        readings += [r for r in fetch_pima_alert() if (r.precip_in or 0) > 0]

    inserted = 0
    for r in readings:
        key = (r.source, r.site_id)
        stamp = r.timestamp.isoformat()
        if seen.get(key) == stamp:
            continue  # unchanged since last poll
        insert_gauge_reading(r)
        seen[key] = stamp
        inserted += 1
    return inserted


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("runner_gauges")

    poll_min = float(os.getenv("GAUGE_POLL_MIN", 15))
    log.info("gauge runner started; poll=%.0fmin, pima_alert=%s", poll_min, pima_alert_enabled())

    shutting_down = False

    def _shutdown(*_):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.info("shutting down")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    seen: dict[tuple[str, str], str] = {}
    backoff = 30
    while not shutting_down:
        try:
            n = _poll_once(seen)
            if n:
                log.info("stored %d new gauge reading(s)", n)
            backoff = 30
        except Exception as exc:  # noqa: BLE001 — keep the loop alive on transient errors
            log.warning("gauge poll error: %s; retrying sooner", exc)
            time.sleep(backoff)
            backoff = min(300, backoff * 2)
            continue
        time.sleep(poll_min * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
