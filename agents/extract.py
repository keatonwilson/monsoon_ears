"""Extraction node: ClassifiedEvent → ExtractedEvent via Haiku + geocoding.

Pulls structured incident details (locations, units, callsigns, severity,
wash/road-closure indicators) out of the raw transcript. The prompt seeds the
model with Tucson-specific wash names and common dispatch codes so the model
recognizes them as entities rather than as ordinary words.

After the LLM call, if the model returned any `locations`, we geocode the
first one via `geopy` + Nominatim with a disk-backed cache to avoid hitting
Nominatim repeatedly for the same address.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from pydantic import BaseModel, Field

from models.schemas import ClassifiedEvent, ExtractedEvent, Severity

logger = logging.getLogger(__name__)

TUCSON_WASHES = (
    "Rillito", "Pantano", "Santa Cruz", "Tanque Verde", "Sabino",
    "Cañada del Oro", "Brawley", "Julian",
)

DISPATCH_CODES_HINT = (
    "code 2 (no lights/sirens), code 3 (lights/sirens), TC (traffic collision), "
    "MVA (motor vehicle accident), 10-50 (accident), 10-52 (ambulance needed)"
)

# Only geocode locations that came from a confidently-classified transmission.
# Garbled transcripts get low classifier confidence; geocoding their nonsense
# "locations" is what filled the cache with junk no-matches.
MIN_GEOCODE_CONFIDENCE = float(os.getenv("MIN_GEOCODE_CONFIDENCE", "0.5"))

_DIGIT_RE = re.compile(r"\d")
_STREET_SUFFIX_RE = re.compile(
    r"\b(st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|way|pl|"
    r"place|ct|court|hwy|highway|fwy|freeway|loop|trail|tr|pkwy|parkway|cir|"
    r"circle|wash)\b",
    re.IGNORECASE,
)
_HIGHWAY_RE = re.compile(r"\b(i-?\d+|interstate\s+\d+|sr-?\d+|us-?\d+)\b", re.IGNORECASE)
_INTERSECTION_RE = re.compile(r"\w+\s+(?:and|&|/|at)\s+\w+", re.IGNORECASE)
_WASH_RE = re.compile("|".join(re.escape(w) for w in TUCSON_WASHES), re.IGNORECASE)


def _looks_geocodable(location: str) -> bool:
    """Cheap gate to skip obvious non-addresses before spending a geocoder call.

    Accepts strings with a house/block number, a street/highway token, an
    intersection ("Speedway and Kolb"), or a known Tucson wash. Rejects short
    all-alpha noise like "northwest Maine" or "coffee depraved" that the
    extractor sometimes emits from garbled audio.
    """
    if not location:
        return False
    s = location.strip()
    if len(s) < 3:
        return False
    return bool(
        _DIGIT_RE.search(s)
        or _STREET_SUFFIX_RE.search(s)
        or _HIGHWAY_RE.search(s)
        or _WASH_RE.search(s)
        or _INTERSECTION_RE.search(s)
    )


class ExtractResponse(BaseModel):
    """Structured output from the extractor — no geocoded lat/lon yet."""
    locations: list[str] = Field(default_factory=list, description="Place names or street addresses mentioned.")
    incident_type: Optional[str] = Field(default=None, description="A short description like 'cardiac arrest' or 'structure fire'.")
    callsigns: list[str] = Field(default_factory=list, description="Radio callsigns (e.g. 'Engine 31', 'Med 843').")
    units: list[str] = Field(default_factory=list, description="Unit designators (overlap with callsigns is fine).")
    status_codes: list[str] = Field(default_factory=list, description="Dispatch codes mentioned literally in the text.")
    severity: Severity = Field(default=Severity.UNKNOWN)
    wash_name: Optional[str] = Field(default=None, description="One of Tucson's named washes if mentioned.")
    road_closure: Optional[bool] = Field(default=None, description="True only if a road closure is explicitly mentioned.")


def _build_prompt(classified: ClassifiedEvent) -> str:
    return (
        "Extract structured incident data from this Tucson public-safety radio transcript.\n\n"
        f"Frequency: {classified.frequency_mhz} MHz\n"
        f"Type: {classified.transmission_type.value}\n"
        f"Text: \"{classified.raw_text}\"\n\n"
        f"Known Tucson washes (flag if mentioned): {', '.join(TUCSON_WASHES)}\n"
        f"Common dispatch shorthand: {DISPATCH_CODES_HINT}\n\n"
        "Return only entities the text actually mentions. Don't invent. If no "
        "location is mentioned, return an empty list. Severity: 'high' for "
        "any life-threat (cardiac, structure fire, flood, MCI); 'medium' for "
        "typical EMS or fire response; 'low' for routine; 'unknown' if "
        "you really can't tell. Set road_closure only if the dispatcher "
        "or units explicitly say a road is closed."
    )


# --- Geocoding ---------------------------------------------------------------

_geocode_lock = Lock()
_geocoder = None
_cache: dict[str, tuple[Optional[float], Optional[float]]] | None = None


def _cache_path() -> Path:
    return Path(os.getenv("GEOCODE_CACHE_PATH", "./data/geocode_cache.json")).expanduser()


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    path = _cache_path()
    if path.exists():
        try:
            _cache = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("geocode cache at %s unreadable, starting fresh", path)
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save_cache() -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_cache, indent=2))


def _miss_ttl_sec() -> float:
    """How long a clean no-match stays cached before we re-query (default 30d).
    Misses expire so a later provider/data improvement can eventually resolve a
    location, while hits are kept forever."""
    raw = os.getenv("GEOCODE_MISS_TTL_SEC")
    try:
        return float(raw) if raw else 30 * 24 * 3600
    except ValueError:
        return 30 * 24 * 3600


def _read_cache_entry(cache: dict, key: str) -> Optional[tuple[Optional[float], Optional[float]]]:
    """Return cached (lat, lon) if a usable entry exists, else None meaning
    "not cached — go query". Handles both the current dict format and the legacy
    `[lat, lon]` list format. A legacy `[None, None]` (a no-match poisoned in by
    the old B2 bug) is treated as expired so it gets re-queried and self-heals."""
    if key not in cache:
        return None
    entry = cache[key]
    if isinstance(entry, list):  # legacy format
        lat, lon = (list(entry) + [None, None])[:2]
        if lat is None or lon is None:
            return None  # poisoned legacy null — re-query
        return (lat, lon)
    if isinstance(entry, dict):
        lat, lon = entry.get("lat"), entry.get("lon")
        if entry.get("status") == "hit":
            return (lat, lon)
        if entry.get("status") == "miss":
            if time.time() - float(entry.get("ts", 0)) < _miss_ttl_sec():
                return (lat, lon)  # still-fresh no-match: (None, None)
            return None  # expired miss — re-query
    return None


def _write_cache_entry(cache: dict, key: str, lat: Optional[float], lon: Optional[float], status: str) -> None:
    cache[key] = {"lat": lat, "lon": lon, "status": status, "ts": time.time()}


def _persist_cache() -> None:
    """Best-effort flush; a write failure must not crash the worker."""
    try:
        _save_cache()
    except OSError as exc:
        logger.warning("could not persist geocode cache: %s", exc)


# Greater Tucson / Pima County bounding box (lat S/N, lon W/E). Generous enough
# to cover Marana, Vail, Green Valley, Saguaro NP; tight enough to reject a
# globally-ambiguous match (a bare street name resolving to another country).
_REGION_LAT = (31.2, 32.85)
_REGION_LON = (-111.65, -110.4)


def _in_region(lat: float, lon: float) -> bool:
    return _REGION_LAT[0] <= lat <= _REGION_LAT[1] and _REGION_LON[0] <= lon <= _REGION_LON[1]


def _default_user_agent() -> str:
    """A *valid* Nominatim UA. The public service 403s placeholder/contact-less
    agents (e.g. the old `contact@example.com` default), which silently zeroed
    out all geocoding during the first soak. Require a real identifier."""
    return os.getenv("NOMINATIM_USER_AGENT", "monsoon-ears/1.0 (+https://github.com/keatonwilson/monsoon_ears)")


def _build_geocoders() -> list[tuple[str, object]]:
    """Provider fallback chain. Nominatim first (best for named/wash locations),
    then ArcGIS and US Census (both keyless, no UA gating) so a single provider
    403'ing or rate-limiting doesn't take all geocoding down. Order/inclusion is
    tunable via GEOCODER_CHAIN (comma-separated: nominatim,arcgis,census)."""
    from geopy.geocoders import ArcGIS, Nominatim

    chain = os.getenv("GEOCODER_CHAIN", "nominatim,arcgis,census")
    out: list[tuple[str, object]] = []
    for name in [c.strip().lower() for c in chain.split(",") if c.strip()]:
        if name == "nominatim":
            out.append(("nominatim", Nominatim(user_agent=_default_user_agent(), timeout=10)))
        elif name == "arcgis":
            out.append(("arcgis", ArcGIS(timeout=10)))
        elif name == "census":
            out.append(("census", _CensusGeocoder()))
    return out


class _CensusGeocoder:
    """Tiny keyless US Census onelineaddress geocoder with a geopy-like result."""

    _URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

    def geocode(self, query: str, timeout: int = 15):
        import requests

        resp = requests.get(
            self._URL,
            params={"address": query, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        coords = matches[0]["coordinates"]
        return type("R", (), {"latitude": coords["y"], "longitude": coords["x"]})()


def _get_geocoders() -> list[tuple[str, object]]:
    global _geocoder
    if _geocoder is None:
        _geocoder = _build_geocoders()
    return _geocoder


def geocode(location: str, geocoder=None) -> tuple[Optional[float], Optional[float]]:
    """Look up a location string. Cache-first, rate-limited, with provider
    fallback so one provider's failure doesn't blank out the coordinate."""
    cache = _load_cache()
    key = f"tucson, az | {location.strip().lower()}"
    hit = _read_cache_entry(cache, key)
    if hit is not None:
        return hit
    with _geocode_lock:
        # Re-check after acquiring lock — another thread may have populated it.
        hit = _read_cache_entry(cache, key)
        if hit is not None:
            return hit

        # An injected geocoder (tests) bypasses the provider chain entirely.
        providers = [("injected", geocoder)] if geocoder is not None else _get_geocoders()

        lat, lon = None, None
        had_clean_response = False  # at least one provider answered without error
        query = f"{location}, Tucson, AZ"
        for name, g in providers:
            try:
                # Nominatim's published policy is 1 req/sec; the keyless fallbacks
                # are politely throttled too. Only sleep before a real call.
                time.sleep(1.0)
                result = g.geocode(query, timeout=10)
            except Exception as exc:  # noqa: BLE001 — try the next provider
                logger.warning("geocode via %s failed for %r: %s — trying next provider",
                               name, location, exc)
                continue
            had_clean_response = True
            if result is not None:
                rlat, rlon = float(result.latitude), float(result.longitude)
                # Bounding-box sanity: a bare street / vague "the wash" can
                # match globally (we saw a -41° latitude). Anything outside
                # the Tucson/Pima region is wrong — treat it as a no-match
                # and let the next provider try.
                if _in_region(rlat, rlon):
                    lat, lon = rlat, rlon
                    break  # got a plausible hit — stop the chain
                logger.debug("geocode: %s returned out-of-region (%.3f,%.3f) for %r — trying next",
                             name, rlat, rlon, location)
                continue
            # A no-match (None) is NOT authoritative: Nominatim often can't
            # parse intersections / vague phrasing that ArcGIS or Census
            # resolve fine. So fall through to the next provider rather than
            # giving up here.
            logger.debug("geocode: %s found no match for %r — trying next", name, location)
            continue
        else:
            logger.debug("geocode: no provider resolved %r", location)

        # Cache policy (the B2 fix): a hit is permanent; a *clean* no-match is
        # cached with a TTL so a later provider/data improvement can resolve it;
        # an all-providers-errored result is NOT cached at all, so a transient
        # outage can't poison the cache permanently the way it used to.
        if lat is not None:
            _write_cache_entry(cache, key, lat, lon, "hit")
            _persist_cache()
        elif had_clean_response:
            _write_cache_entry(cache, key, None, None, "miss")
            _persist_cache()
        return (lat, lon)


# --- Public API --------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def extract_event(
    classified: ClassifiedEvent,
    client=None,
    model: Optional[str] = None,
    geocoder=None,
    skip_geocode: bool = False,
) -> ExtractedEvent:
    """Extract structured fields and optionally geocode the first location."""
    client = client if client is not None else _get_client()
    model_name = model or os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001")

    response = client.messages.create(
        model=model_name,
        max_tokens=512,
        messages=[{"role": "user", "content": _build_prompt(classified)}],
        response_model=ExtractResponse,
    )

    lat: Optional[float] = None
    lon: Optional[float] = None
    # Only geocode when the classifier was confident and the string actually
    # looks like a place — garbled, low-confidence transcripts otherwise fill
    # the cache with junk no-matches (A2). Take the first address-like location.
    if not skip_geocode and (classified.confidence or 0.0) >= MIN_GEOCODE_CONFIDENCE:
        for loc in response.locations:
            if _looks_geocodable(loc):
                lat, lon = geocode(loc, geocoder=geocoder)
                break

    return ExtractedEvent(
        **classified.model_dump(),
        locations=response.locations,
        incident_type=response.incident_type,
        callsigns=response.callsigns,
        units=response.units,
        status_codes=response.status_codes,
        severity=response.severity,
        lat=lat,
        lon=lon,
        wash_name=response.wash_name,
        road_closure=response.road_closure,
    )
