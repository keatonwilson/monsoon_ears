"""30-second sanity check: capture, demod, write WAVs to /tmp.

No DB, no Whisper. Use this on the Pi to confirm the SDR + demod chain
produces intelligible audio before running the full pipeline.

    uv run python scripts/smoke_capture.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

# Make the repo root importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.capture_analog import AnalogCapture  # noqa: E402
from ingestion.preprocess import preprocess_radio_audio  # noqa: E402


def write_wav(path: Path, audio: np.ndarray, sr: int = 16000) -> None:
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    freq_mhz = float(os.getenv("CAPTURE_FREQ_MHZ", 154.370))
    chunk_sec = float(os.getenv("CHUNK_DURATION_SEC", 5))
    total_sec = 30

    out_dir = Path("/tmp")
    label = os.getenv("CAPTURE_LABEL", f"{freq_mhz:.4f}".replace(".", "_"))
    capture = AnalogCapture(freq_mhz=freq_mhz)
    print(f"capturing {total_sec}s @ {freq_mhz:.4f} MHz (label={label})")

    start = time.time()
    chunk_idx = 0
    try:
        while time.time() - start < total_sec:
            chunk = capture.read_chunk_full(chunk_sec)
            cleaned = preprocess_radio_audio(chunk.audio)
            # Write every chunk during calibration so we can listen to noise too.
            path = out_dir / f"smoke_{label}_{chunk_idx:02d}.wav"
            write_wav(path, cleaned)
            tag = "SQUELCHED" if chunk.squelched else "PASS"
            print(
                f"chunk {chunk_idx:02d}: iq_power={chunk.iq_power:.5f} "
                f"audio_rms={chunk.audio_rms:.4f} {tag} -> {path.name}"
            )
            chunk_idx += 1
    finally:
        capture.close()
    print(f"done. wrote chunks to {out_dir}/smoke_{label}_*.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())
