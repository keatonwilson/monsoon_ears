"""Prompt-caching helpers for the Anthropic / instructor calls.

Wraps a static instruction prefix in a `cache_control`-tagged ``system`` block
so repeated calls that share an identical prefix are billed at the ~0.1x
cache-read rate instead of full input price. Two cautions are baked in here:

* Caching is a *prefix* match. The cached block must be byte-identical across
  calls and must physically precede any per-call data — so we only ever cache
  the static instruction text and keep the volatile event data in the user
  message. Anything that varies per request (timestamps, the actual events)
  must stay out of the system block.
* A prefix only caches once it exceeds the model's minimum cacheable length
  (Sonnet 4.6: 2048 tokens; Haiku 4.5: 4096). Below that the API silently
  declines to cache — no error, just ``cache_creation_input_tokens: 0``. Short
  prompts wrapped here are harmless but simply won't cache until they grow past
  the floor (the shared Tucson context prefix is the prompt that clears it).

TTL: the default ephemeral cache lives 5 minutes. The monsoon digest runs every
15 minutes — longer than that — so its prefix would expire between runs and
never hit. Pass ``ttl="1h"`` for the digest so 3 of every 4 runs read the cache;
leave the default 5-minute TTL for bursty interactive paths (NL->SQL, the
classify/extract stream during active traffic).
"""

from __future__ import annotations

from typing import Optional


def cached_system(text: str, ttl: Optional[str] = None) -> list[dict]:
    """Return a single-block ``system`` list tagged for prompt caching.

    ``ttl`` is either ``None`` (default 5-minute ephemeral cache) or ``"1h"``
    (extended cache, for prefixes reused on a >5-minute cadence).
    """
    cache_control: dict = {"type": "ephemeral"}
    if ttl:
        cache_control["ttl"] = ttl
    return [{"type": "text", "text": text, "cache_control": cache_control}]
