"""Phase 03 analog ingestion loop: scanner → VAD → Whisper → SQLite.

The scanner walks the analog FM target list, holds on whatever channel has
signal, and periodically visits NOAA for forecast context. Each captured
chunk goes through the same preprocess → VAD → Whisper → hallucination filter
chain as Phase 02 — the only difference is that `frequency_mhz` on the stored
row varies with which channel was active.

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

from config.frequencies import ANALOG_FM, Frequency
from db.queries import insert_transcription
from ingestion.capture_analog import AnalogCapture
from ingestion.preprocess import preprocess_radio_audio
from ingestion.scanner import FrequencyScanner
from ingestion.transcribe import transcribe
from ingestion.vad import find_speech_segments
from models.schemas import TranscriptionEvent

# Priority floor parsing — higher floors keep fewer (more important) freqs.
_PRIORITY_ORDER = {"primary": 0, "high": 1, "medium": 2, "low": 3}


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _scan_list(min_priority: str) -> list[Frequency]:
    floor = _PRIORITY_ORDER.get(min_priority.lower(), _PRIORITY_ORDER["high"])
    return [
        f for f in ANALOG_FM
        if _PRIORITY_ORDER.get(f.priority, 99) <= floor
        # NOAA is excluded from the rolling scan — handled as a periodic visit.
        and abs(f.mhz - 162.3975) > 0.01
    ]


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("runner_analog")

    sample_rate = int(os.getenv("SDR_SAMPLE_RATE", 1_024_000))
    gain_raw = os.getenv("SDR_GAIN", "40")
    gain: float | str = "auto" if gain_raw.lower() == "auto" else float(gain_raw)
    chunk_sec = float(os.getenv("CHUNK_DURATION_SEC", 15))
    noise_floor_rms = float(os.getenv("NOISE_FLOOR_RMS", 0.65))
    vad_aggressiveness = int(os.getenv("VAD_AGGRESSIVENESS", 2))
    vad_min_segment_ms = int(os.getenv("VAD_MIN_SEGMENT_MS", 1500))

    scan_min_priority = os.getenv("SCAN_MIN_PRIORITY", "high")
    probe_sec = float(os.getenv("SCAN_PROBE_SEC", 1.0))
    hangover_chunks = int(os.getenv("SCAN_HANGOVER_CHUNKS", 2))
    max_hold_sec = float(os.getenv("SCAN_MAX_HOLD_SEC", 120.0))
    noaa_freq_mhz = float(os.getenv("NOAA_FREQ_MHZ", 162.3975))
    noaa_interval_min = float(os.getenv("NOAA_VISIT_INTERVAL_MIN", 15.0))
    noaa_duration_sec = float(os.getenv("NOAA_VISIT_DURATION_SEC", 60.0))

    scan_freqs = _scan_list(scan_min_priority)
    if not scan_freqs:
        log.error("no frequencies match SCAN_MIN_PRIORITY=%s", scan_min_priority)
        return 1

    log.info(
        "scan list (%d freqs, min_priority=%s): %s",
        len(scan_freqs), scan_min_priority,
        ", ".join(f"{f.name}@{f.mhz}" for f in scan_freqs),
    )

    # The scanner needs a tuner; we kick off on the first scan freq, then it
    # retunes as state transitions happen.
    capture = AnalogCapture(
        freq_mhz=scan_freqs[0].mhz,
        sample_rate=sample_rate,
        gain=gain,
        noise_floor_rms=noise_floor_rms,
    )
    scanner = FrequencyScanner(
        backend=capture,
        scan_frequencies=scan_freqs,
        noaa_freq_mhz=noaa_freq_mhz,
        probe_sec=probe_sec,
        hangover_chunks=hangover_chunks,
        max_hold_sec=max_hold_sec,
        noaa_visit_interval_min=noaa_interval_min,
        noaa_visit_duration_sec=noaa_duration_sec,
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

    log.info("starting scanner loop, chunk=%.1fs, vad_aggr=%d, vad_min=%dms",
             chunk_sec, vad_aggressiveness, vad_min_segment_ms)
    try:
        for active in scanner.iter_active_chunks(chunk_sec):
            cleaned = preprocess_radio_audio(active.audio, sr=capture.audio_rate)

            # NOAA broadcasts continuously; VAD-segmenting it produces a stack of
            # mid-sentence fragments. For NOAA visits we transcribe the whole
            # captured window as one block and trust Whisper's own internal VAD.
            is_noaa = active.frequency.agency == "NOAA"
            if is_noaa:
                segments_audio: list[tuple] = [(cleaned, cleaned.size / capture.audio_rate)]
            else:
                segs = find_speech_segments(
                    cleaned,
                    aggressiveness=vad_aggressiveness,
                    min_segment_ms=vad_min_segment_ms,
                )
                if not segs:
                    log.debug("no speech in %.4f MHz chunk", active.frequency.mhz)
                    continue
                segments_audio = [
                    (cleaned[s.start_sample : s.end_sample],
                     (s.end_sample - s.start_sample) / capture.audio_rate)
                    for s in segs
                ]

            for seg_audio, duration_sec in segments_audio:
                text = transcribe(seg_audio, sr=capture.audio_rate)
                if not text:
                    continue
                if duration_sec < 1.0:
                    log.debug("skipping <1s yielded segment")
                    continue
                event = TranscriptionEvent(
                    timestamp=datetime.now(timezone.utc),
                    frequency_mhz=active.frequency.mhz,
                    raw_text=text,
                    duration_sec=duration_sec,
                    source="analog",
                )
                row_id = insert_transcription(event)
                log.info(
                    "[%.4f / %s] id=%d (%.1fs) %s",
                    active.frequency.mhz, active.frequency.name,
                    row_id, duration_sec, text[:120],
                )
    finally:
        capture.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
