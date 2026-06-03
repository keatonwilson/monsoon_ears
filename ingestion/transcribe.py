"""Whisper transcription with built-in hallucination filtering.

Whisper happily emits ghost text when fed silence/noise (e.g. lone Chinese
characters, "you", "Thanks for watching!"). The model exposes per-segment
diagnostics that catch most of these:

  * no_speech_prob       — likelihood the segment is non-speech (silence/noise)
  * avg_logprob          — mean token log-probability; low = uncertain output
  * compression_ratio    — gzip ratio of the text; high = repetitive babble

We use the same thresholds the OpenAI Whisper reference implementation uses
internally for its "did the model just hallucinate?" check.

Two interchangeable decode backends, selected by ``WHISPER_BACKEND``:

  * ``openai`` (default) — the reference ``openai-whisper`` package (PyTorch).
  * ``faster`` — ``faster-whisper`` (CTranslate2). 3-4x faster on the Pi 5 CPU
    at int8, which is what makes ``medium`` feasible inline (``small`` on the
    reference backend is the prior sweet spot). Same model names, same
    per-segment diagnostics, so the gates below are backend-agnostic.

Both expose identical per-segment diagnostics, so everything below the decode
step (``TranscriptionResult`` + ``_is_hallucination``) is shared.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

from agents.hallucination import _HALLUCINATION_PHRASES

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
LOGPROB_DROP_THRESHOLD = -1.1
COMPRESSION_RATIO_THRESHOLD = 2.4
# Below this fraction of letters/digits/spaces, the text is mostly punctuation
# or symbol garble — a common Whisper-on-noise failure mode. Env-overridable.
MIN_ALPHA_RATIO = 0.6

_WORD_RE = re.compile(r"[A-Za-z']+")

# NOTE: we deliberately do NOT pass a Whisper `initial_prompt`. We tried seeding
# one with Tucson scanner vocabulary (agencies, codes, washes) to bias decoding,
# but Whisper treats `initial_prompt` as prior context and *continues it
# verbatim* on near-silent audio — the seed text leaked back out as fake
# high-confidence "transmissions" (e.g. "Rural Metro, Northwest Fire, and AMR
# units respond code 3 to structure fires…" classified fire @ 0.95). This
# recurred even with the prompt written as prose, so the seeding was removed.
# The real lever for decode quality is a larger model (small -> medium), not a
# prompt. See memory: whisper-initial-prompt-leak.

_model = None


def _backend() -> str:
    """Which decode backend to use: 'openai' (default) or 'faster'."""
    return os.getenv("WHISPER_BACKEND", "openai").strip().lower()


def get_model():
    """Lazy-load the Whisper model (slow first call, ~244 MB for small).

    The model object differs per backend (a ``whisper.Whisper`` vs a
    ``faster_whisper.WhisperModel``); ``_decode`` knows how to drive each.
    """
    global _model
    if _model is None:
        model_name = os.getenv("WHISPER_MODEL", "small")
        if _backend() == "faster":
            from faster_whisper import WhisperModel

            device = os.getenv("WHISPER_DEVICE", "cpu")
            compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
            logger.info("loading faster-whisper model: %s (device=%s, compute=%s)",
                        model_name, device, compute_type)
            _model = WhisperModel(model_name, device=device, compute_type=compute_type)
        else:
            import whisper

            logger.info("loading openai-whisper model: %s", model_name)
            _model = whisper.load_model(model_name)
    return _model


@dataclass
class _Segment:
    """Normalized per-segment diagnostics, identical across both backends."""
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float


def _decode(model, audio: np.ndarray) -> tuple[str, list[_Segment]]:
    """Run the configured backend and normalize its output to (text, segments).

    Keeps the two libraries' differing return shapes (openai's dict vs
    faster-whisper's (generator, info) tuple) out of the rest of the module.
    """
    if _backend() == "faster":
        beam = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
        seg_iter, _info = model.transcribe(audio, language="en", beam_size=beam)
        segs = [
            _Segment(
                text=s.text or "",
                no_speech_prob=s.no_speech_prob,
                avg_logprob=s.avg_logprob,
                compression_ratio=s.compression_ratio,
            )
            for s in seg_iter  # generator — consuming it runs the decode
        ]
        return "".join(s.text for s in segs).strip(), segs

    # openai-whisper
    result = model.transcribe(audio, language="en", fp16=False)
    raw = result.get("segments") or []
    segs = [
        _Segment(
            text=s.get("text", ""),
            no_speech_prob=s.get("no_speech_prob", 0.0),
            avg_logprob=s.get("avg_logprob", 0.0),
            compression_ratio=s.get("compression_ratio", 0.0),
        )
        for s in raw
    ]
    return (result.get("text") or "").strip(), segs


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


def _text_noise_reason(text: str) -> Optional[str]:
    """Content-based noise heuristics on the decoded text itself (independent of
    Whisper's confidence scores). Catches boilerplate leakage, symbol garble,
    and single-word stutters that still score an OK avg_logprob."""
    stripped = text.strip()
    lowered = stripped.lower()
    # Known YouTube/boilerplate leakage (shared with the LLM-stage gate).
    if any(p in lowered for p in _HALLUCINATION_PHRASES):
        return "boilerplate phrase"
    # Mostly non-letter garble (punctuation/symbol soup from pure noise).
    alpha_ratio_t = _env_float("MIN_ALPHA_RATIO", MIN_ALPHA_RATIO)
    usable = sum(c.isalnum() or c.isspace() for c in stripped)
    if stripped and usable / len(stripped) < alpha_ratio_t:
        return f"low_alpha_ratio={usable / len(stripped):.2f}"
    # A single word repeated ("yeah yeah yeah", "okay okay okay") — Whisper's
    # classic loop on tones/static. Two+ distinct words clears this.
    words = [w.lower() for w in _WORD_RE.findall(stripped)]
    if len(words) >= 3 and len(set(words)) == 1:
        return f"repeated_word={words[0]!r}"
    return None


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
    # Content-based gates (boilerplate, symbol soup, single-word loops).
    text_reason = _text_noise_reason(r.text)
    if text_reason:
        return text_reason
    return None


def transcribe(audio: np.ndarray, sr: int = 16000) -> Optional[str]:
    """Transcribe mono float32 audio. Returns text, or None if hallucinated."""
    if audio is None or audio.size == 0:
        return None
    if sr != 16000:
        raise ValueError(f"Whisper expects 16 kHz audio, got {sr}")

    model = get_model()
    text, segments = _decode(model, audio.astype(np.float32))

    if not segments:
        # No segments == Whisper found nothing worth transcribing.
        return None

    parsed = TranscriptionResult(
        text=text,
        no_speech_prob=max(s.no_speech_prob for s in segments),
        avg_logprob=float(np.mean([s.avg_logprob for s in segments])),
        compression_ratio=max(s.compression_ratio for s in segments),
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
