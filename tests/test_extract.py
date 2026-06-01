"""extract_event tests — mocked LLM, geocoding via fake geocoder + disk cache."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agents.extract import ExtractResponse, extract_event, geocode
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


def _classified(text="Med 843, respond code 2, TC unknown, 205 W Irvington Rd") -> ClassifiedEvent:
    return ClassifiedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text=text,
        duration_sec=4.0,
        transmission_type=TransmissionType.EMS,
        confidence=0.9,
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


def test_default_user_agent_is_not_placeholder(monkeypatch):
    """Regression: the public Nominatim 403s contact-less / example.com agents,
    which silently zeroed geocoding in the first soak."""
    import agents.extract as ex
    monkeypatch.delenv("NOMINATIM_USER_AGENT", raising=False)
    ua = ex._default_user_agent()
    assert "example.com" not in ua
    assert "monsoon-ears" in ua


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
