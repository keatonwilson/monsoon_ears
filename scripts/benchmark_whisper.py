"""Benchmark Whisper decode backends/models on real audio (run on the Pi).

Compares wall-clock decode time (and the transcript itself) across the openai
and faster backends and a set of model sizes, so the small->medium + faster
migration (handoff #13 / A1) is a measured decision, not a guess. The pipeline
runs Whisper *inline* per call, so the figure that matters is the realtime
ratio: seconds-of-compute per second-of-audio must stay well under 1.0 to keep
up with live traffic.

Usage (on the Pi, where the `pi` extra + ctranslate2 are installed):
    uv run python scripts/benchmark_whisper.py path/to/clip.wav
    uv run python scripts/benchmark_whisper.py clip.wav \
        --backends openai,faster --models small,small.en,medium

Audio is loaded as 16 kHz mono float32 (Whisper's expected input). Without a
file argument it synthesizes 15s of noise — useful only for timing, not quality.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave

import numpy as np


def load_audio(path: str | None, seconds: float) -> tuple[np.ndarray, float]:
    """Return (mono float32 @ 16 kHz, duration_sec). Synthesizes noise if no path."""
    if path is None:
        n = int(16000 * seconds)
        rng = np.random.default_rng(0)
        return (rng.standard_normal(n) * 0.05).astype(np.float32), seconds

    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        ch = w.getnchannels()
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:  # cheap linear resample to 16 kHz
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    return audio, len(audio) / 16000.0


def run_openai(model_name: str, audio: np.ndarray) -> tuple[float, float, str]:
    import whisper
    t0 = time.monotonic()
    model = whisper.load_model(model_name)
    load_t = time.monotonic() - t0
    t1 = time.monotonic()
    result = model.transcribe(audio, language="en", fp16=False)
    return time.monotonic() - t1, load_t, (result.get("text") or "").strip()


def run_faster(model_name: str, audio: np.ndarray, compute_type: str) -> tuple[float, float, str]:
    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
    load_t = time.monotonic() - t0
    t1 = time.monotonic()
    seg_iter, _info = model.transcribe(audio, language="en", beam_size=5)
    text = "".join(s.text for s in seg_iter).strip()
    return time.monotonic() - t1, load_t, text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio", nargs="?", help="WAV file (16 kHz mono ideal); omit for noise")
    ap.add_argument("--seconds", type=float, default=15.0, help="synthetic clip length")
    ap.add_argument("--backends", default="openai,faster")
    ap.add_argument("--models", default="small,small.en,medium")
    ap.add_argument("--compute-type", default="int8", help="faster-whisper compute type")
    args = ap.parse_args()

    audio, dur = load_audio(args.audio, args.seconds)
    print(f"audio: {dur:.1f}s @ 16 kHz ({args.audio or 'synthetic noise'})\n")
    print(f"{'backend':8} {'model':10} {'load_s':>7} {'decode_s':>9} {'xRT':>6}  transcript")
    print("-" * 80)

    for backend in [b.strip() for b in args.backends.split(",") if b.strip()]:
        for model_name in [m.strip() for m in args.models.split(",") if m.strip()]:
            try:
                if backend == "faster":
                    decode_t, load_t, text = run_faster(model_name, audio, args.compute_type)
                else:
                    decode_t, load_t, text = run_openai(model_name, audio)
            except Exception as exc:  # noqa: BLE001 — report and continue the grid
                print(f"{backend:8} {model_name:10}  ERROR: {exc}")
                continue
            xrt = decode_t / dur if dur else float("nan")
            print(f"{backend:8} {model_name:10} {load_t:7.1f} {decode_t:9.1f} {xrt:6.2f}  "
                  f"{text[:60]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
