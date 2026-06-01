"""Whisper transcription with built-in hallucination filtering.

Whisper happily emits ghost text when fed silence/noise (e.g. lone Chinese
characters, "you", "Thanks for watching!"). The model exposes per-segment
diagnostics that catch most of these:

  * no_speech_prob       — likelihood the segment is non-speech (silence/noise)
  * avg_logprob          — mean token log-probability; low = uncertain output
  * compression_ratio    — gzip ratio of the text; high = repetitive babble

We use the same thresholds the OpenAI Whisper reference implementation uses
internally for its "did the model just hallucinate?" check.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Whisper's own defaults from whisper/transcribe.py. All four are overridable
# via env (see `_env_float`) so the hallucination gates can be tuned on the Pi
# without a code change.
NO_SPEECH_THRESHOLD = 0.6
LOGPROB_THRESHOLD = -1.0
# Standalone low-confidence drop: garble that the model thinks is speech (low
# no_speech_prob) still tends to score a poor avg_logprob. Drop anything below
# this regardless of no_speech_prob. Stricter than LOGPROB_THRESHOLD so it only
# fires on clearly low-confidence output — real dispatch traffic scores higher.
LOGPROB_DROP_THRESHOLD = -1.2
COMPRESSION_RATIO_THRESHOLD = 2.4

# Seed Whisper's decoder with Tucson scanner vocabulary so domain terms decode
# ("Tanque Verde", "code 3") instead of garbling. Deliberately written as a
# short, natural-prose sentence rather than comma-separated keyword lists:
# Whisper treats the prompt as prior context and will happily *continue* a list
# verbatim as if it were speech, so a list of streets/washes leaks back out as a
# fake high-confidence transmission on near-silent audio. Prose with the terms
# woven in biases the token prior just as well without the echo failure mode.
TUCSON_PROMPT = (
    "Tucson, Arizona emergency scanner traffic. Tucson Fire, Rural Metro, "
    "Northwest Fire, and AMR units respond code 2 or code 3 to structure fires, "
    "traffic collisions, cardiac calls, and water rescues in washes like the "
    "Rillito and the Tanque Verde."
)

_model = None


def get_model():
    """Lazy-load the Whisper model (slow first call, ~244 MB for small)."""
    global _model
    if _model is None:
        import whisper

        model_name = os.getenv("WHISPER_MODEL", "small")
        logger.info("loading whisper model: %s", model_name)
        _model = whisper.load_model(model_name)
    return _model


@dataclass
class TranscriptionResult:
    text: str
    no_speech_prob: float    # max across segments
    avg_logprob: float       # mean across segments
    compression_ratio: float # max across segments
    n_segments: int


def _env_float(name: str, default: float) -> float:
    """Read a float threshold from env, falling back to `default` on unset or
    unparseable values (a bad override must not silently disable a gate)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r, using default %s", name, raw, default)
        return default


def _is_hallucination(r: TranscriptionResult) -> Optional[str]:
    """Return a reason string if the result looks hallucinated, else None."""
    no_speech_t = _env_float("NO_SPEECH_THRESHOLD", NO_SPEECH_THRESHOLD)
    logprob_t = _env_float("LOGPROB_THRESHOLD", LOGPROB_THRESHOLD)
    logprob_drop_t = _env_float("LOGPROB_DROP_THRESHOLD", LOGPROB_DROP_THRESHOLD)
    compression_t = _env_float("COMPRESSION_RATIO_THRESHOLD", COMPRESSION_RATIO_THRESHOLD)

    if not r.text:
        return "empty"
    # Whisper's own silence check: high no_speech_prob AND low confidence.
    if r.no_speech_prob > no_speech_t and r.avg_logprob < logprob_t:
        return f"no_speech_prob={r.no_speech_prob:.2f} logprob={r.avg_logprob:.2f}"
    # Standalone low-confidence drop: catches garble the model reads as speech
    # (low no_speech_prob) but still scores poorly.
    if r.avg_logprob < logprob_drop_t:
        return f"low_confidence logprob={r.avg_logprob:.2f}"
    # Repetitive babble check.
    if r.compression_ratio > compression_t:
        return f"compression_ratio={r.compression_ratio:.2f}"
    # Very short outputs on noise are usually hallucinations (single CJK char,
    # lone "You", etc.). Two-character minimum is generous; real dispatch
    # transmissions are always longer.
    if len(r.text) < 3:
        return f"too_short ({len(r.text)} chars)"
    return None


def transcribe(audio: np.ndarray, sr: int = 16000) -> Optional[str]:
    """Transcribe mono float32 audio. Returns text, or None if hallucinated."""
    if audio is None or audio.size == 0:
        return None
    if sr != 16000:
        raise ValueError(f"Whisper expects 16 kHz audio, got {sr}")

    model = get_model()
    result = model.transcribe(
        audio.astype(np.float32),
        language="en",
        fp16=False,
        initial_prompt=TUCSON_PROMPT,
    )
    segments = result.get("segments") or []
    text = (result.get("text") or "").strip()

    if not segments:
        # No segments == Whisper found nothing worth transcribing.
        return None

    parsed = TranscriptionResult(
        text=text,
        no_speech_prob=max(s.get("no_speech_prob", 0.0) for s in segments),
        avg_logprob=float(np.mean([s.get("avg_logprob", 0.0) for s in segments])),
        compression_ratio=max(s.get("compression_ratio", 0.0) for s in segments),
        n_segments=len(segments),
    )

    reason = _is_hallucination(parsed)
    if reason:
        logger.info("dropping hallucination (%s): %r", reason, text[:60])
        return None

    logger.debug(
        "transcribed (%d seg, nsp=%.2f lp=%.2f cr=%.2f): %s",
        parsed.n_segments, parsed.no_speech_prob, parsed.avg_logprob,
        parsed.compression_ratio, text[:80],
    )
    return text
