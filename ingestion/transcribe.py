"""Whisper transcription wrapper. Model is loaded once and reused."""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

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


def transcribe(audio: np.ndarray, sr: int = 16000) -> Optional[str]:
    """Transcribe a chunk of mono float32 audio at `sr` Hz. Returns text or None."""
    if audio is None or audio.size == 0:
        return None
    if sr != 16000:
        raise ValueError(f"Whisper expects 16 kHz audio, got {sr}")

    model = get_model()
    # Whisper accepts a float32 np array in [-1, 1].
    result = model.transcribe(audio.astype(np.float32), language="en", fp16=False)
    text = (result.get("text") or "").strip()
    return text or None
