"""Phase 02 analog ingestion loop: capture → preprocess → Whisper → SQLite.

Run with:
    uv run python -m ingestion.runner_analog
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from db.queries import insert_transcription
from ingestion.capture_analog import AnalogCapture
from ingestion.preprocess import preprocess_radio_audio
from ingestion.transcribe import transcribe
from models.schemas import TranscriptionEvent

# Rural Metro Fire Dispatch — confirmed analog FM during Phase 01.
DEFAULT_FREQ_MHZ = 154.370


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("runner_analog")

    freq_mhz = float(os.getenv("CAPTURE_FREQ_MHZ", DEFAULT_FREQ_MHZ))
    sample_rate = int(os.getenv("SDR_SAMPLE_RATE", 1_024_000))
    gain_raw = os.getenv("SDR_GAIN", "40")
    gain: float | str = "auto" if gain_raw.lower() == "auto" else float(gain_raw)
    chunk_sec = float(os.getenv("CHUNK_DURATION_SEC", 8))
    silence_threshold = float(os.getenv("SILENCE_THRESHOLD", 0.01))
    min_duration = float(os.getenv("SILENCE_MIN_DURATION", 1.5))

    capture = AnalogCapture(
        freq_mhz=freq_mhz,
        sample_rate=sample_rate,
        gain=gain,
        silence_threshold=silence_threshold,
    )

    def _shutdown(*_):
        log.info("shutting down")
        capture.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("starting capture loop @ %.4f MHz, chunk=%.1fs", freq_mhz, chunk_sec)
    try:
        for audio in capture.iter_chunks(chunk_sec):
            if audio is None:
                continue
            duration = audio.size / capture.audio_rate
            if duration < min_duration:
                log.debug("skipping short chunk %.2fs", duration)
                continue

            cleaned = preprocess_radio_audio(audio, sr=capture.audio_rate)
            text = transcribe(cleaned, sr=capture.audio_rate)
            if not text:
                log.debug("whisper returned empty text")
                continue

            event = TranscriptionEvent(
                timestamp=datetime.now(timezone.utc),
                frequency_mhz=freq_mhz,
                raw_text=text,
                duration_sec=duration,
                source="analog",
            )
            row_id = insert_transcription(event)
            log.info("[%s] id=%d (%.1fs) %s", freq_mhz, row_id, duration, text[:120])
    finally:
        capture.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
