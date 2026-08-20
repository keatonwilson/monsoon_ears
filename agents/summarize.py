"""Thread summarizer agent.

A `EventThreadRow` is a same-frequency cluster of `TranscriptionEventRow`s
captured within `THREAD_GAP_SEC` of each other. The summarizer reads all the
fragmented utterances inside a thread and asks Haiku 4.5 to consolidate them
into a single coherent narrative the dashboard can show in place of the
individual rows.

This runs every worker poll cycle on closed-and-unsummarized threads, and on
demand via `/summarize?thread_id=X` (which clears `summarized_at` and re-runs).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from config.locale import GEOCODE_QUERY_SUFFIX
from db.queries import (
    events_for_thread,
    threads_needing_summary,
    update_thread_summary,
)
from models.schemas import Severity, TransmissionType

logger = logging.getLogger(__name__)


class ThreadSummary(BaseModel):
    """Structured output the model returns for a thread."""
    summary: str = Field(
        ...,
        description="One- to three-sentence plain-English narrative describing "
                    "what happened in this thread. No quoting; reconstruct the "
                    "incident from fragments.",
    )
    transmission_type: TransmissionType = Field(default=TransmissionType.UNKNOWN)
    severity: Severity = Field(default=Severity.UNKNOWN)
    locations: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    incident_type: Optional[str] = Field(
        default=None, description="Short label e.g. 'cardiac arrest', 'structure fire'.",
    )
    is_noise: bool = Field(
        default=False,
        description="True if these fragments are just noise / unintelligible "
                    "garble with no real incident (the dashboard hides these by "
                    "default). False for any genuine transmission.",
    )


def _build_prompt(rows) -> str:
    bullets = []
    for r in rows:
        ts = r.timestamp.strftime("%H:%M:%S") if r.timestamp else "?"
        type_hint = f"[{r.transmission_type}]" if r.transmission_type else ""
        bullets.append(f"  - {ts} {type_hint} {r.raw_text}")

    freq = rows[0].frequency_mhz
    return (
        "These are radio transmission fragments captured on a public-safety "
        f"channel in {GEOCODE_QUERY_SUFFIX}. All on {freq} MHz, ordered in time:\n\n"
        + "\n".join(bullets)
        + "\n\nReconstruct what happened in 1–3 plain-English sentences. "
          "Connect fragments where they obviously refer to the same incident. "
          "Don't quote verbatim; paraphrase clearly. If the fragments are "
          "noise or unintelligible, say so concisely and set is_noise=true. "
          "Identify locations, units, severity, and a short incident_type label."
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def summarize_thread(
    thread_id: int,
    client=None,
    model: Optional[str] = None,
) -> Optional[ThreadSummary]:
    """Generate and persist a summary for a single thread."""
    rows = events_for_thread(thread_id)
    if not rows:
        logger.info("summarize_thread(%d): no events, skipping", thread_id)
        return None
    client = client if client is not None else _get_client()
    model_name = model or os.getenv(
        "SUMMARIZE_MODEL",
        os.getenv("CLASSIFY_MODEL", "claude-haiku-4-5-20251001"),
    )
    response: ThreadSummary = client.messages.create(
        model=model_name,
        max_tokens=512,
        messages=[{"role": "user", "content": _build_prompt(rows)}],
        response_model=ThreadSummary,
    )
    update_thread_summary(
        thread_id,
        summary=response.summary,
        transmission_type=response.transmission_type.value if response.transmission_type else None,
        severity=response.severity.value if response.severity else None,
        locations=response.locations or None,
        units=response.units or None,
        incident_type=response.incident_type,
        is_noise=response.is_noise,
    )
    logger.info(
        "summarize_thread(%d, %d events): %s",
        thread_id, len(rows), response.summary[:80],
    )
    return response


def summarize_pending(limit: int = 10, client=None) -> int:
    """Summarize up to `limit` closed-and-unsummarized threads. Returns count
    of threads processed. Called from the agent worker on every poll."""
    pending = threads_needing_summary(limit=limit)
    count = 0
    for thread in pending:
        try:
            summarize_thread(thread.id, client=client)
            count += 1
        except Exception:  # noqa: BLE001
            logger.exception("error summarizing thread %d", thread.id)
    return count
