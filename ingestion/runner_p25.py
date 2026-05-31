"""P25 (PCWIN) ingestion loop: op25 → WAV dir → Whisper → SQLite.

Mirrors `runner_analog.py`, but the decode is done by op25 (a separate native
process) rather than our own DSP. This runner watches the directory op25 writes
per-call WAVs into and feeds each call through the shared transcription path,
storing rows with `source="p25"` and the real `talkgroup_id`.

op25 itself must be built and locked onto PCWIN first — see
`deploy/op25_setup.md`. This runner does NOT build op25; it either launches a
preconfigured op25 command (`OP25_CMD`) or, if that's empty, assumes op25 runs
as its own service and just consumes its WAV output.

Run with:
    P25_WAV_DIR=/tmp/op25_calls uv run python -m ingestion.runner_p25
"""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import sys

from dotenv import load_dotenv

from ingestion.capture_p25 import (
    OP25_AUDIO_SR,
    UdpP25Backend,
    WavDirBackend,
    run_p25_ingestion,
)

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
    log = logging.getLogger("runner_p25")

    op25_cmd = os.getenv("OP25_CMD", "").strip()

    op25_proc: subprocess.Popen | None = None
    if op25_cmd:
        log.info("launching op25: %s", op25_cmd)
        op25_proc = subprocess.Popen(shlex.split(op25_cmd))
    else:
        log.info("OP25_CMD empty; assuming op25 runs separately")

    # Backend selection. The real op25 `-U` path streams PCM over UDP (default);
    # WavDirBackend remains for a hypothetical per-call WAV recorder setup.
    backend_kind = os.getenv("P25_BACKEND", "udp").strip().lower()
    if backend_kind == "wavdir":
        wav_dir = os.getenv("P25_WAV_DIR", "./data/op25_calls")
        poll_sec = float(os.getenv("P25_POLL_SEC", 1.0))
        backend = WavDirBackend(wav_dir, poll_sec=poll_sec)
        log.info("p25 backend=wavdir watching %s", wav_dir)
    else:
        backend = UdpP25Backend(
            udp_host=os.getenv("P25_UDP_HOST", "127.0.0.1"),
            udp_port=int(os.getenv("P25_UDP_PORT", 23456)),
            console_url=os.getenv("P25_CONSOLE_URL", "http://127.0.0.1:8080") or None,
            src_sample_rate=int(os.getenv("P25_AUDIO_SR", OP25_AUDIO_SR)),
            gap_sec=float(os.getenv("P25_GAP_SEC", 0.8)),
        )
        log.info("p25 backend=udp port=%s console=%s",
                 os.getenv("P25_UDP_PORT", "23456"), os.getenv("P25_CONSOLE_URL", "http://127.0.0.1:8080"))

    shutting_down = False

    def _shutdown(*_):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.info("shutting down")
        backend.close()
        if op25_proc is not None and op25_proc.poll() is None:
            op25_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("starting p25 ingestion (backend=%s)", backend_kind)
    try:
        run_p25_ingestion(backend)
    finally:
        backend.close()
        if op25_proc is not None and op25_proc.poll() is None:
            op25_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
