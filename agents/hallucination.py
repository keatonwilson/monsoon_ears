"""Shared Whisper-hallucination heuristics.

Whisper occasionally invents fluent-sounding fragments from FM noise: short
nonsensical phrases ("potatoes", "Yeti Planet"), YouTube boilerplate
("thanks for watching"), or CJK characters bleeding in from the model's
multilingual training. A real Tucson dispatch always carries a unit number,
address, or street name — i.e. at least one digit OR enough words to be more
than a stray hallucinated token.

This gate is applied at two stages so a ghost transmission can never become a
false HIGH-severity alert:

* `agents/classify.py` uses it as a *pre-gate* — flagged text short-circuits to
  `TransmissionType.UNKNOWN` with `confidence=0.0` and never reaches the LLM.
* `agents/alert.py` uses it (plus `MIN_ALERT_CONFIDENCE`) as the *safety net* —
  flagged or low-confidence events never fire a push, even if `extract`
  somehow assigned HIGH severity.

The ingest-stage filter in `ingestion/transcribe.py` (`_is_hallucination`) is
the first line of defense; this module catches what slips past it.
"""

from __future__ import annotations

import re
from typing import Optional

_CJK_RE = re.compile(r"[　-鿿가-힯]")
_DIGIT_RE = re.compile(r"\d")
_HALLUCINATION_PHRASES = {
    # Whisper's well-known YouTube-transcript leakage.
    "thanks for watching",
    "thank you for watching",
    "subscribe",
    "like and subscribe",
    "images in the description",
    "link in the description",
}

_MIN_ALERT_WORDS = 5  # below this, almost always Whisper noise

# Below this classifier confidence we refuse to escalate an event to a push,
# even if extract tagged it HIGH. A genuine dispatch on a known channel scores
# well above this; uncertain ghosts score low.
MIN_ALERT_CONFIDENCE = 0.35


def looks_like_hallucination(raw_text: Optional[str]) -> bool:
    """Heuristic: would a real dispatch ever look like this?

    True ⇒ treat as noise. Real dispatches name a unit/address/street, so we
    require either >=5 word tokens with a digit somewhere, or >=8 word tokens
    without one. Anything containing CJK or known YouTube boilerplate is out.
    """
    if not raw_text:
        return True
    text = raw_text.strip()
    if not text:
        return True
    if _CJK_RE.search(text):
        return True
    lowered = text.lower()
    if any(p in lowered for p in _HALLUCINATION_PHRASES):
        return True
    words = text.split()
    if len(words) < _MIN_ALERT_WORDS:
        return True
    # Real dispatches almost always have an address number or unit ID. If we
    # got 5–7 words and zero digits, that's usually still noise.
    if len(words) < 8 and not _DIGIT_RE.search(text):
        return True
    return False
