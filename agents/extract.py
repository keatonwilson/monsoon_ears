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
    if key in cache:
        cached = cache[key]
        return (cached[0], cached[1])
    with _geocode_lock:
        # Re-check after acquiring lock — another thread may have populated it.
        if key in cache:
            cached = cache[key]
            return (cached[0], cached[1])

        # An injected geocoder (tests) bypasses the provider chain entirely.
        providers = [("injected", geocoder)] if geocoder is not None else _get_geocoders()

        lat, lon = None, None
        query = f"{location}, Tucson, AZ"
        for name, g in providers:
            try:
                # Nominatim's published policy is 1 req/sec; the keyless fallbacks
                # are politely throttled too. Only sleep before a real call.
                time.sleep(1.0)
                result = g.geocode(query, timeout=10)
                if result is not None:
                    lat, lon = float(result.latitude), float(result.longitude)
                    break  # got a hit — stop the chain
                # A no-match (None) is NOT authoritative: Nominatim often can't
                # parse intersections / vague phrasing that ArcGIS or Census
                # resolve fine. So fall through to the next provider rather than
                # giving up here.
                logger.debug("geocode: %s found no match for %r — trying next", name, location)
                continue
            except Exception as exc:  # noqa: BLE001 — try the next provider
                logger.warning("geocode via %s failed for %r: %s — trying next provider",
                               name, location, exc)
                continue
        else:
            logger.debug("geocode: no provider resolved %r", location)

        cache[key] = [lat, lon]
        try:
            _save_cache()
        except OSError as exc:
            logger.warning("could not persist geocode cache: %s", exc)
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
    if response.locations and not skip_geocode:
        lat, lon = geocode(response.locations[0], geocoder=geocoder)

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
