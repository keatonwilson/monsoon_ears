"""APRS-IS client: stream Tucson-area packets from the internet APRS feed.

APRS-IS is the public aggregation of every APRS packet heard by any internet-
connected gateway worldwide. Subscribing with a server-side filter
(`r/<lat>/<lon>/<km>`) gives us all Tucson-area weather stations, mobile
tracks, and bulletins without needing a second RTL-SDR dongle.

The connection is read-only and anonymous (`callsign='N0CALL', passwd='-1'`).
aprslib calls a callback for each parsed packet; we shape the relevant fields
into an `APRSEvent` and write it to the same `aprs_events` table that the
voice pipeline already shares.

Run with:
    APRS_IS_ENABLED=true uv run python -m ingestion.aprs_is_client
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from db.queries import insert_aprs
from models.schemas import APRSEvent

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def packet_to_event(packet: dict) -> APRSEvent | None:
    """Translate an aprslib packet dict to APRSEvent. Returns None if unparseable."""
    callsign = packet.get("from")
    if not callsign:
        return None

    weather = packet.get("weather") or {}
    return APRSEvent(
        timestamp=datetime.now(timezone.utc),
        callsign=str(callsign),
        lat=packet.get("latitude"),
        lon=packet.get("longitude"),
        symbol=packet.get("symbol"),
        comment=(packet.get("comment") or "")[:512] or None,
        # APRS spec puts these in imperial. aprslib carries them through.
        temp_f=weather.get("temperature"),
        rainfall_in=weather.get("rain_1h"),
        wind_mph=weather.get("wind_speed"),
    )


def _make_callback(stats: dict):
    def _on_packet(packet):
        try:
            event = packet_to_event(packet)
            if event is None:
                return
            insert_aprs(event)
            stats["count"] += 1
            if stats["count"] % 25 == 0:
                logger.info("APRS-IS: %d packets ingested", stats["count"])
        except Exception:  # noqa: BLE001
            logger.exception("error handling APRS packet: %r", packet)
    return _on_packet


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("aprs_is")

    if os.getenv("APRS_IS_ENABLED", "false").lower() != "true":
        log.info("APRS_IS_ENABLED=false; exiting (set true to start the feed)")
        return 0

    callsign = os.getenv("APRS_IS_CALLSIGN", "N0CALL")
    filter_str = os.getenv("APRS_IS_FILTER", "r/32.2/-110.9/50")
    server = os.getenv("APRS_IS_SERVER", "rotate.aprs.net")

    import aprslib

    stats = {"count": 0}

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

    backoff_sec = 5
    while not shutting_down:
        try:
            log.info("APRS-IS connecting to %s with filter %s as %s",
                     server, filter_str, callsign)
            ais = aprslib.IS(callsign, passwd="-1", host=server, port=14580)
            ais.set_filter(filter_str)
            ais.connect()
            ais.consumer(_make_callback(stats), raw=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("APRS-IS connection error: %s; retrying in %ds", exc, backoff_sec)
            time.sleep(backoff_sec)
            backoff_sec = min(60, backoff_sec * 2)
            continue
        # consumer() returned cleanly — happens on close. Reset backoff and reconnect.
        backoff_sec = 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
