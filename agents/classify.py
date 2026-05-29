"""Classification node: TranscriptionEvent → ClassifiedEvent via Haiku.

Uses `instructor.from_anthropic` to enforce a small Pydantic response schema
at the API boundary. The classifier sees both the raw text and the frequency
context — knowing we're listening to `154.370 MHz` is a strong prior for
"Rural Metro Fire" / "AMR EMS" output classes.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from config.frequencies import ANALOG_FM
from models.schemas import ClassifiedEvent, TranscriptionEvent, TransmissionType

logger = logging.getLogger(__name__)

_FREQ_HINTS = {f.mhz: f"{f.name} ({f.agency})" for f in ANALOG_FM}


class ClassifyResponse(BaseModel):
    """Structured output from the classifier — three fields, nothing else."""
    transmission_type: TransmissionType = Field(
        ..., description="Which category of public-safety transmission this is."
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="How confident, 0.0 (no idea) to 1.0 (certain).",
    )
    language: str = Field(
        default="en", description="ISO 639-1 code; almost always 'en' for our channels."
    )


def _build_prompt(event: TranscriptionEvent) -> str:
    hint = _FREQ_HINTS.get(event.frequency_mhz, "unknown channel")
    return (
        f"You are classifying a snippet from a public-safety radio scanner in Tucson, AZ.\n\n"
        f"Frequency: {event.frequency_mhz} MHz — {hint}\n"
        f"Duration: {event.duration_sec:.1f} seconds\n"
        f"Transcribed text:\n\"{event.raw_text}\"\n\n"
        "Pick the single best `transmission_type` from: fire, ems, police, ham, "
        "weather, aprs, flood_control, unknown. The frequency hint is a strong prior — "
        "trust it unless the text clearly says otherwise. Estimate confidence 0.0–1.0."
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def classify_event(
    event: TranscriptionEvent,
    client=None,
    model: Optional[str] = None,
) -> ClassifiedEvent:
    """Classify a transcription. Pass `client` to inject a mock in tests."""
    client = client if client is not None else _get_client()
    model_name = model or os.getenv("CLASSIFY_MODEL", "claude-haiku-4-5-20251001")

    response = client.messages.create(
        model=model_name,
        max_tokens=256,
        messages=[{"role": "user", "content": _build_prompt(event)}],
        response_model=ClassifyResponse,
    )
    logger.debug(
        "classify(%s) -> %s @ %.2f",
        event.raw_text[:60], response.transmission_type.value, response.confidence,
    )
    return ClassifiedEvent(
        **event.model_dump(),
        transmission_type=response.transmission_type,
        confidence=response.confidence,
        language=response.language,
    )
