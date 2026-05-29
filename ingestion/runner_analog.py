"""Phase 02 analog ingestion loop: capture → squelch → VAD → Whisper → SQLite.

Each chunk that survives the RMS squelch is segmented by webrtcvad. Whisper
runs once per speech segment instead of once per fixed window — fewer mid-word
cuts, less wasted compute on dead air, fewer hallucinations.

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
from ingestion.vad import find_speech_segments
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
    chunk_sec = float(os.getenv("CHUNK_DURATION_SEC", 15))
    noise_floor_rms = float(os.getenv("NOISE_FLOOR_RMS", 0.65))
    vad_aggressiveness = int(os.getenv("VAD_AGGRESSIVENESS", 2))
    vad_min_segment_ms = int(os.getenv("VAD_MIN_SEGMENT_MS", 800))

    capture = AnalogCapture(
        freq_mhz=freq_mhz,
        sample_rate=sample_rate,
        gain=gain,
        noise_floor_rms=noise_floor_rms,
    )

    shutting_down = False

    def _shutdown(*_):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.info("shutting down")
        capture.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info(
        "starting capture loop @ %.4f MHz, chunk=%.1fs, vad_aggr=%d, vad_min=%dms",
        freq_mhz, chunk_sec, vad_aggressiveness, vad_min_segment_ms,
    )
    try:
        for audio in capture.iter_chunks(chunk_sec):
            if audio is None:
                continue
            cleaned = preprocess_radio_audio(audio, sr=capture.audio_rate)
            segments = find_speech_segments(
                cleaned,
                aggressiveness=vad_aggressiveness,
                min_segment_ms=vad_min_segment_ms,
            )
            if not segments:
                log.debug("chunk had no speech segments after VAD")
                continue

            for seg in segments:
                seg_audio = cleaned[seg.start_sample : seg.end_sample]
                duration_sec = seg_audio.size / capture.audio_rate
                text = transcribe(seg_audio, sr=capture.audio_rate)
                if not text:
                    continue
                event = TranscriptionEvent(
                    timestamp=datetime.now(timezone.utc),
                    frequency_mhz=freq_mhz,
                    raw_text=text,
                    duration_sec=duration_sec,
                    source="analog",
                )
                row_id = insert_transcription(event)
                log.info(
                    "[%s] id=%d (%.1fs) %s",
                    freq_mhz, row_id, duration_sec, text[:120],
                )
    finally:
        capture.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
