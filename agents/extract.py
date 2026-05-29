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


def _get_geocoder():
    global _geocoder
    if _geocoder is None:
        from geopy.geocoders import Nominatim
        user_agent = os.getenv("NOMINATIM_USER_AGENT", "monsoon-ears/0.1")
        _geocoder = Nominatim(user_agent=user_agent)
    return _geocoder


def geocode(location: str, geocoder=None) -> tuple[Optional[float], Optional[float]]:
    """Look up a location string. Cache-first, rate-limited (1 req/sec)."""
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
        try:
            g = geocoder if geocoder is not None else _get_geocoder()
            time.sleep(1.0)  # Nominatim's published 1 req/sec policy.
            result = g.geocode(f"{location}, Tucson, AZ", timeout=10)
            if result is None:
                lat, lon = None, None
            else:
                lat, lon = float(result.latitude), float(result.longitude)
        except Exception as exc:  # noqa: BLE001 — network errors must not crash worker
            logger.warning("geocode failed for %r: %s", location, exc)
            lat, lon = None, None
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
