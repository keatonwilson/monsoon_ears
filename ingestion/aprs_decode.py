"""APRS packet ingestion skeleton.

Phase 02: gated by APRS_ENABLED=true. Real implementation waits for a 2nd
RTL-SDR dongle so we can monitor 144.390 MHz simultaneously with the analog
voice channel — a single dongle can only tune one frequency at a time.

When implemented, the chain will be:
    RTL-SDR @ 144.390 MHz → FM demod → multimon-ng (or direwolf) AFSK1200
    → KISS frames → aprs3.parse() → APRSEvent → insert_aprs()

Run with:
    APRS_ENABLED=true uv run python -m ingestion.aprs_decode
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    if os.getenv("APRS_ENABLED", "false").lower() != "true":
        logger.info("APRS disabled (set APRS_ENABLED=true to attempt). Exiting.")
        return 0

    logger.warning(
        "APRS capture is not yet implemented — requires a 2nd RTL-SDR dongle "
        "plus an AFSK1200 demodulator (multimon-ng or direwolf). See module "
        "docstring for the planned pipeline."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
