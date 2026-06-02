"""APRS-IS client: stream Tucson-area packets from the internet APRS feed.

APRS-IS is the public aggregation of every APRS packet heard by any internet-
connected gateway worldwide. Subscribing with a server-side filter
(`r/<lat>/<lon>/<km>`) gives us all Tucson-area weather stations, mobile
tracks, and bulletins without needing a second RTL-SDR dongle.

The connection defaults to read-only and anonymous (`callsign='N0CALL',
passwd='-1'`). Set `APRS_IS_CALLSIGN` to your own licensed callsign to be a good
APRS-IS citizen — identifying yourself avoids future server-side filtering of
anonymous clients. A passcode of `-1` keeps the login receive-only (you cannot
inject packets), which is exactly what we want; set `APRS_IS_PASSCODE` to your
verified passcode only if you ever need to transmit. aprslib calls a callback
for each parsed packet; we shape the relevant fields into an `APRSEvent` and
write it to the same `aprs_events` table that the voice pipeline already shares.

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


# Plausible Tucson-area surface readings. A value outside these bounds means
# the packet was mis-decoded (or a sensor faulted); we drop it rather than feed
# garbage into the map tooltips and the Sonnet monsoon digest.
_TEMP_F_MIN, _TEMP_F_MAX = -40.0, 140.0
_RAIN_IN_MAX = 30.0  # a single hour over the all-time US record is impossible
_WIND_MPH_MAX = 250.0


def _c_to_f(c: float | None) -> float | None:
    return None if c is None else c * 9.0 / 5.0 + 32.0


def _mm_to_in(mm: float | None) -> float | None:
    return None if mm is None else mm / 25.4


def _mps_to_mph(mps: float | None) -> float | None:
    return None if mps is None else mps * 2.2369362920544


def _sane(value: float | None, lo: float, hi: float) -> float | None:
    """Return value if within [lo, hi], else None (drop the bad reading)."""
    if value is None:
        return None
    return value if lo <= value <= hi else None


def packet_to_event(packet: dict) -> APRSEvent | None:
    """Translate an aprslib packet dict to APRSEvent. Returns None if unparseable.

    Verified against aprslib 0.7.2: it parses the wire weather fields (which APRS
    encodes in °F / hundredths-of-inch / mph) and *normalizes them to metric*
    (°C, mm, m/s) before handing them to us — so the conversions below are the
    correct round-trip back to the imperial units our columns store. We also
    sanity-clamp each field so a mis-decoded packet can't poison the dashboard
    or the monsoon digest.
    """
    callsign = packet.get("from")
    if not callsign:
        return None

    weather = packet.get("weather") or {}
    rain_in = _mm_to_in(weather.get("rain_1h"))
    wind_mph = _mps_to_mph(weather.get("wind_speed"))
    return APRSEvent(
        timestamp=datetime.now(timezone.utc),
        callsign=str(callsign),
        lat=packet.get("latitude"),
        lon=packet.get("longitude"),
        symbol=packet.get("symbol"),
        comment=(packet.get("comment") or "")[:512] or None,
        temp_f=_sane(_c_to_f(weather.get("temperature")), _TEMP_F_MIN, _TEMP_F_MAX),
        rainfall_in=_sane(rain_in, 0.0, _RAIN_IN_MAX),
        wind_mph=_sane(wind_mph, 0.0, _WIND_MPH_MAX),
    )


def aprs_login_params() -> tuple[str, str, str, str]:
    """Resolve the APRS-IS login from env: (callsign, passcode, server, filter).

    Defaults are anonymous receive-only (`N0CALL` / `-1`). A real callsign with
    passcode `-1` identifies us without granting injection rights — the
    recommended posture for a listen-only feed.
    """
    callsign = os.getenv("APRS_IS_CALLSIGN", "N0CALL").strip() or "N0CALL"
    passcode = os.getenv("APRS_IS_PASSCODE", "-1").strip() or "-1"
    server = os.getenv("APRS_IS_SERVER", "rotate.aprs.net")
    filter_str = os.getenv("APRS_IS_FILTER", "r/32.2/-110.9/50")
    return callsign, passcode, server, filter_str


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

    callsign, passcode, server, filter_str = aprs_login_params()
    if callsign == "N0CALL":
        log.info("APRS-IS using anonymous N0CALL (receive-only). Set "
                 "APRS_IS_CALLSIGN to your callsign to identify the feed.")
    elif passcode == "-1":
        log.info("APRS-IS identifying as %s, receive-only (passcode -1)", callsign)
    else:
        log.info("APRS-IS authenticating as %s with a verified passcode", callsign)

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
            ais = aprslib.IS(callsign, passwd=passcode, host=server, port=14580)
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
