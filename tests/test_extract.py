"""extract_event tests — mocked LLM, geocoding via fake geocoder + disk cache."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agents.extract import (
    ExtractResponse,
    _looks_geocodable,
    extract_event,
    geocode,
)
from models.schemas import (
    ClassifiedEvent,
    ExtractedEvent,
    Severity,
    TranscriptionEvent,
    TransmissionType,
)


class FakeMessages:
    def __init__(self, response: ExtractResponse):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: ExtractResponse):
        self.messages = FakeMessages(response)


class FakeGeocoder:
    """Returns a canned coordinate, records lookups."""

    def __init__(self, lat=32.2226, lon=-110.9747):
        self.lat = lat
        self.lon = lon
        self.queries: list[str] = []

    def geocode(self, query, timeout=10):
        self.queries.append(query)
        return SimpleNamespace(latitude=self.lat, longitude=self.lon)


@pytest.fixture(autouse=True)
def _isolate_geocode_cache(tmp_path, monkeypatch):
    """Point the cache at a tmp file and reset module-level state per test."""
    monkeypatch.setenv("GEOCODE_CACHE_PATH", str(tmp_path / "geocode.json"))
    import agents.extract as ex
    ex._cache = None
    ex._geocoder = None
    monkeypatch.setattr("agents.extract.time.sleep", lambda _s: None)  # no-op the 1s rate-limit
    yield
    ex._cache = None
    ex._geocoder = None


def _classified(
    text="Med 843, respond code 2, TC unknown, 205 W Irvington Rd",
    confidence=0.9,
) -> ClassifiedEvent:
    return ClassifiedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text=text,
        duration_sec=4.0,
        transmission_type=TransmissionType.EMS,
        confidence=confidence,
    )


def test_extract_returns_extracted_event_with_response_fields():
    response = ExtractResponse(
        locations=["205 W Irvington Rd"],
        incident_type="traffic collision",
        callsigns=["Med 843"],
        units=["Med 843"],
        status_codes=["code 2", "TC"],
        severity=Severity.MEDIUM,
        wash_name=None,
        road_closure=False,
    )
    client = FakeClient(response)
    geocoder = FakeGeocoder(lat=32.18, lon=-111.00)
    out = extract_event(_classified(), client=client, geocoder=geocoder)
    assert isinstance(out, ExtractedEvent)
    assert out.units == ["Med 843"]
    assert out.lat == 32.18 and out.lon == -111.00
    # The geocoder was called with the location text + "Tucson, AZ".
    assert any("Irvington" in q for q in geocoder.queries)


def test_extract_skips_geocode_when_no_locations():
    response = ExtractResponse(severity=Severity.UNKNOWN)
    client = FakeClient(response)
    geocoder = FakeGeocoder()
    out = extract_event(_classified("nothing to see here"), client=client, geocoder=geocoder)
    assert out.lat is None
    assert geocoder.queries == []


def test_geocode_uses_cache_on_repeat():
    geocoder = FakeGeocoder()
    lat1, lon1 = geocode("205 W Irvington Rd", geocoder=geocoder)
    lat2, lon2 = geocode("205 W Irvington Rd", geocoder=geocoder)
    assert (lat1, lon1) == (lat2, lon2)
    assert len(geocoder.queries) == 1  # cached on second call


class _BoomGeocoder:
    """Always raises — simulates a provider 403/outage."""

    def __init__(self):
        self.queries: list[str] = []

    def geocode(self, query, timeout=10):
        self.queries.append(query)
        raise RuntimeError("403 Access denied")


def test_geocode_falls_back_to_next_provider(monkeypatch):
    """First provider 403s; the chain moves on and the second provider hits."""
    import agents.extract as ex
    boom = _BoomGeocoder()
    good = FakeGeocoder(lat=32.25, lon=-110.92)
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("boom", boom), ("good", good)])

    lat, lon = geocode("River Rd at Campbell")
    assert (lat, lon) == (32.25, -110.92)
    assert boom.queries and good.queries  # both were tried, in order


def test_geocode_all_providers_fail_returns_none(monkeypatch):
    import agents.extract as ex
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("boom", _BoomGeocoder())])
    assert geocode("Nowhere St") == (None, None)


class _NoMatchGeocoder:
    """Returns None (clean no-match), like Nominatim on an unparseable address."""

    def __init__(self):
        self.queries: list[str] = []

    def geocode(self, query, timeout=10):
        self.queries.append(query)
        return None


def test_geocode_continues_past_clean_no_match(monkeypatch):
    """A None (no-match) from one provider must NOT stop the chain — the next
    provider gets a shot (the bug that filled 0 rows in the first backfill)."""
    import agents.extract as ex
    nomatch = _NoMatchGeocoder()
    good = FakeGeocoder(lat=32.28, lon=-110.94)
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("nomatch", nomatch), ("good", good)])

    lat, lon = geocode("River Rd and Campbell Ave")
    assert (lat, lon) == (32.28, -110.94)
    assert nomatch.queries and good.queries  # both consulted


def test_default_user_agent_is_not_placeholder(monkeypatch):
    """Regression: the public Nominatim 403s contact-less / example.com agents,
    which silently zeroed geocoding in the first soak."""
    import agents.extract as ex
    monkeypatch.delenv("NOMINATIM_USER_AGENT", raising=False)
    ua = ex._default_user_agent()
    assert "example.com" not in ua
    assert "monsoon-ears" in ua


def test_geocode_rejects_out_of_region_match(monkeypatch):
    """A provider hit outside the Tucson/Pima bbox (e.g. a -41° latitude) is
    discarded and the chain falls through to a provider that returns a local hit."""
    import agents.extract as ex
    wrong = FakeGeocoder(lat=-41.27, lon=174.78)   # Wellington, NZ
    right = FakeGeocoder(lat=32.22, lon=-110.97)    # Tucson
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("wrong", wrong), ("right", right)])
    lat, lon = geocode("River Rd")
    assert (lat, lon) == (32.22, -110.97)


def test_geocode_out_of_region_only_returns_none(monkeypatch):
    import agents.extract as ex
    wrong = FakeGeocoder(lat=-41.27, lon=174.78)
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("wrong", wrong)])
    assert geocode("Somewhere ambiguous") == (None, None)


def test_extract_prompt_seeds_tucson_washes():
    response = ExtractResponse()
    client = FakeClient(response)
    extract_event(_classified(), client=client, skip_geocode=True)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "Rillito" in prompt
    assert "Pantano" in prompt
    assert "TC (traffic collision)" in prompt


def test_extract_includes_raw_text_for_fixture_samples(transcripts_by_category):
    """Each flood-control fixture's transcript reaches the extractor prompt."""
    response = ExtractResponse()
    for rec in transcripts_by_category("flood_control"):
        classified = _classified(rec["raw_text"])
        client = FakeClient(response)
        extract_event(classified, client=client, skip_geocode=True)
        prompt = client.messages.calls[0]["messages"][0]["content"]
        assert rec["raw_text"] in prompt


# --- A2: confidence + address-like gating -------------------------------------

@pytest.mark.parametrize("loc", [
    "205 W Irvington Rd",        # house number
    "Speedway and Kolb",         # intersection
    "Grant & Oracle",            # intersection (ampersand)
    "Rillito",                   # named wash
    "I-10 near Ina",             # highway
    "River Road",                # street suffix
])
def test_looks_geocodable_accepts_addresses(loc):
    assert _looks_geocodable(loc)


@pytest.mark.parametrize("loc", [
    "northwest Maine",
    "coffee depraved",
    "the location",
    "ab",
    "",
])
def test_looks_geocodable_rejects_noise(loc):
    assert not _looks_geocodable(loc)


def test_extract_skips_geocode_below_confidence():
    response = ExtractResponse(locations=["205 W Irvington Rd"], severity=Severity.LOW)
    client = FakeClient(response)
    geocoder = FakeGeocoder()
    out = extract_event(_classified(confidence=0.3), client=client, geocoder=geocoder)
    assert out.lat is None and out.lon is None
    assert geocoder.queries == []  # low confidence — never reached the geocoder


def test_extract_skips_geocode_for_non_address_location():
    response = ExtractResponse(locations=["northwest Maine"], severity=Severity.LOW)
    client = FakeClient(response)
    geocoder = FakeGeocoder()
    out = extract_event(_classified(), client=client, geocoder=geocoder)
    assert out.lat is None
    assert geocoder.queries == []  # junk string never geocoded


def test_extract_geocodes_first_address_like_location():
    # The first entry is noise; the extractor should fall through to the address.
    response = ExtractResponse(locations=["the area", "205 W Irvington Rd"], severity=Severity.MEDIUM)
    client = FakeClient(response)
    geocoder = FakeGeocoder(lat=32.18, lon=-111.00)
    out = extract_event(_classified(), client=client, geocoder=geocoder)
    assert (out.lat, out.lon) == (32.18, -111.00)
    assert geocoder.queries and "Irvington" in geocoder.queries[0]


# --- B2: cache poisoning fix --------------------------------------------------

def test_geocode_does_not_cache_provider_error(monkeypatch):
    """A provider outage must NOT be cached — the next call re-queries (B2)."""
    import agents.extract as ex
    boom = _BoomGeocoder()
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("boom", boom)])
    assert geocode("Speedway and Kolb") == (None, None)
    assert geocode("Speedway and Kolb") == (None, None)
    assert len(boom.queries) == 2  # re-queried, not poisoned-cached


def test_geocode_caches_clean_miss_then_requeries_after_ttl(monkeypatch):
    """A clean no-match is cached (no re-query within TTL) but expires."""
    import agents.extract as ex
    nomatch = _NoMatchGeocoder()
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("nomatch", nomatch)])

    assert geocode("Speedway and Kolb") == (None, None)
    assert geocode("Speedway and Kolb") == (None, None)
    assert len(nomatch.queries) == 1  # second call served from cache

    monkeypatch.setenv("GEOCODE_MISS_TTL_SEC", "0")  # everything is now expired
    assert geocode("Speedway and Kolb") == (None, None)
    assert len(nomatch.queries) == 2  # re-queried after TTL


def test_geocode_legacy_null_entry_is_requeried(monkeypatch):
    """Legacy [None, None] entries (poisoned by the old bug) self-heal."""
    import agents.extract as ex
    ex._cache = {"tucson, az | speedway and kolb": [None, None]}
    good = FakeGeocoder(lat=32.25, lon=-110.92)
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("good", good)])
    assert geocode("Speedway and Kolb") == (32.25, -110.92)
    assert good.queries  # the poisoned null did not short-circuit


def test_geocode_legacy_hit_entry_is_served(monkeypatch):
    """Legacy [lat, lon] hits stay valid without a re-query."""
    import agents.extract as ex
    ex._cache = {"tucson, az | river road": [32.30, -110.95]}
    good = FakeGeocoder()
    monkeypatch.setattr(ex, "_get_geocoders", lambda: [("good", good)])
    assert geocode("River Road") == (32.30, -110.95)
    assert good.queries == []  # served from legacy cache
