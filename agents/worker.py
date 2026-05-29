"""Polling worker: fetch unclassified rows, run the agent graph, sleep, repeat.

Runs APScheduler in the background for the monsoon digest job. The main loop
processes new transcriptions sequentially — Anthropic latency dominates and
parallelism here would only complicate error handling.

Run with:
    uv run python -m agents.worker
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

from agents.alert import monsoon_digest
from agents.graph import run_for_row
from db.queries import fetch_unclassified

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("worker")

    poll_sec = float(os.getenv("WORKER_POLL_SEC", 5))
    digest_min = int(os.getenv("DIGEST_INTERVAL_MIN", 15))
    batch_size = int(os.getenv("WORKER_BATCH_SIZE", 10))

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        monsoon_digest,
        trigger="interval",
        minutes=digest_min,
        id="monsoon_digest",
        # Don't run the digest on startup — wait one interval so we have data.
        next_run_time=None,
    )
    scheduler.start()
    log.info(
        "worker started; poll=%.1fs batch=%d digest_every=%dmin",
        poll_sec, batch_size, digest_min,
    )

    shutting_down = False

    def _shutdown(*_):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.info("shutting down")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            rows = fetch_unclassified(limit=batch_size)
            if rows:
                log.info("processing %d unclassified rows", len(rows))
            for row in rows:
                try:
                    final = run_for_row(row.id)
                    classified = final.get("classified")
                    extracted = final.get("extracted")
                    alert = final.get("alert")
                    log.info(
                        "[row %d] type=%s severity=%s alert=%s | %s",
                        row.id,
                        classified.transmission_type.value if classified else "?",
                        extracted.severity.value if extracted else "?",
                        alert.should_alert if alert else "?",
                        (row.raw_text or "")[:80],
                    )
                except Exception:  # noqa: BLE001 — keep the worker alive
                    log.exception("error processing row %d; will retry next poll", row.id)
            time.sleep(poll_sec)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
