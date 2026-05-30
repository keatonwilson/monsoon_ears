"""alert.py tests: rule eval, Ntfy push (mocked), monsoon_digest (mocked LLM)."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.alert import (
    DigestResponse,
    evaluate_alert,
    looks_like_hallucination,
    monsoon_digest,
    push_ntfy,
)
from models.schemas import ExtractedEvent, Severity, TransmissionType


def _extracted(**overrides) -> ExtractedEvent:
    base = dict(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="placeholder",
        duration_sec=2.0,
        transmission_type=TransmissionType.EMS,
        confidence=0.9,
        severity=Severity.MEDIUM,
        road_closure=False,
    )
    base.update(overrides)
    return ExtractedEvent(**base)


# --- evaluate_alert ----------------------------------------------------------


def test_evaluate_alert_medium_severity_does_not_fire():
    decision = evaluate_alert(_extracted())
    assert decision.should_alert is False


def test_evaluate_alert_high_severity_fires():
    decision = evaluate_alert(_extracted(
        severity=Severity.HIGH,
        raw_text="Engine 4 respond to structure fire at 5502 East 22nd Street",
    ))
    assert decision.should_alert is True
    assert decision.reason == "severity=HIGH"
    assert "structure fire" in (decision.summary or "")


def test_evaluate_alert_road_closure_fires():
    decision = evaluate_alert(_extracted(
        road_closure=True,
        raw_text="River Road closed at Campbell due to flooding over the wash",
    ))
    assert decision.should_alert is True
    assert "road_closure" in (decision.reason or "")


# --- Whisper hallucination gate ---------------------------------------------


@pytest.mark.parametrize("text", [
    "potatoes",
    "Yeti Planet",
    "Ah You",
    "life.",
    "diox",
    "Images in the description",
    "Thanks for watching!",
    "Meth準備 respond 102wy",  # CJK leakage
    "",
    None,
])
def test_hallucination_gate_blocks_garbage(text):
    assert looks_like_hallucination(text) is True


@pytest.mark.parametrize("text", [
    "MADS-882 respond to 5502 East 22nd Street with Tucson Fire",
    "Med Day for 6, respond to 8307 south of Placides and Ardo with two's on fire",
    "Engine 4 responding code 3 to River Road and Campbell",
    "Rillito wash flooded over at La Cholla; road closed",
])
def test_hallucination_gate_allows_real_dispatches(text):
    assert looks_like_hallucination(text) is False


def test_evaluate_alert_suppresses_hallucinated_high_severity():
    decision = evaluate_alert(_extracted(severity=Severity.HIGH, raw_text="potatoes"))
    assert decision.should_alert is False
    assert "low-quality" in (decision.reason or "")


# --- push_ntfy ---------------------------------------------------------------


class FakeRequests:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.posts: list[dict] = []

    def post(self, url, data, headers, timeout):
        self.posts.append({"url": url, "data": data, "headers": headers})

        class Resp:
            status_code = self.status_code
            text = ""
        # workaround for closure capture
        Resp.status_code = self.status_code
        return Resp()


def test_push_ntfy_sends_request():
    fr = FakeRequests()
    ok = push_ntfy(
        "Title", "Body", topic="my-topic", base_url="https://ntfy.sh",
        requests_module=fr,
    )
    assert ok
    assert fr.posts[0]["url"] == "https://ntfy.sh/my-topic"
    assert fr.posts[0]["headers"]["Title"] == "Title"


def test_push_ntfy_skips_unconfigured_topic():
    fr = FakeRequests()
    ok = push_ntfy("T", "B", topic=None, requests_module=fr)
    assert ok is False
    assert fr.posts == []


def test_push_ntfy_skips_placeholder_topic():
    fr = FakeRequests()
    ok = push_ntfy("T", "B", topic="monsoon-ears-CHANGE-ME", requests_module=fr)
    assert ok is False
    assert fr.posts == []


# --- monsoon_digest ----------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    yield db_file
    database_module._engine = None


class FakeDigestMessages:
    def __init__(self, response: DigestResponse):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeDigestClient:
    def __init__(self, response: DigestResponse):
        self.messages = FakeDigestMessages(response)


def test_monsoon_digest_no_activity_returns_no_alert(temp_db):
    """Empty DB → digest short-circuits without calling the LLM."""
    client = FakeDigestClient(DigestResponse(should_alert=True))  # would alert if called
    decision = monsoon_digest(client=client)
    assert decision.should_alert is False
    assert decision.reason == "no recent activity"
    assert client.messages.calls == []


def test_monsoon_digest_calls_llm_when_activity_present(temp_db, monkeypatch):
    """With recent fire/EMS rows, digest renders the prompt and calls Sonnet."""
    from db.database import TranscriptionEventRow, get_session

    now = datetime.now(timezone.utc)
    with get_session() as s:
        s.add(TranscriptionEventRow(
            timestamp=now - timedelta(minutes=5),
            frequency_mhz=154.37, raw_text="rillito wash flooded, road closed",
            duration_sec=3.0, transmission_type="flood_control",
        ))
        s.commit()

    response = DigestResponse(
        should_alert=True, summary="Flash flood activity near Rillito",
        correlation_note="No APRS rainfall correlated", reason="manual"
    )
    client = FakeDigestClient(response)
    # No real Ntfy push during tests
    monkeypatch.setattr("agents.alert.push_ntfy", lambda **kwargs: True)

    decision = monsoon_digest(client=client)
    assert decision.should_alert is True
    assert "Rillito" in (decision.summary or "")
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "rillito wash flooded" in prompt
