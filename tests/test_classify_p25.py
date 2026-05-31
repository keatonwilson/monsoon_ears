"""classify prompt uses the talkgroup hint for P25 events (the P25 analogue of
the analog frequency hint)."""

from datetime import datetime, timezone

from agents.classify import ClassifyResponse, classify_event
from models.schemas import TranscriptionEvent, TransmissionType


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _p25_event(tgid: int) -> TranscriptionEvent:
    return TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=0.0,
        raw_text="Engine 1 on scene, working structure fire",
        duration_sec=4.0,
        source="p25",
        talkgroup_id=tgid,
    )


def test_p25_prompt_includes_talkgroup_hint():
    client = _FakeClient(ClassifyResponse(transmission_type=TransmissionType.FIRE, confidence=0.9))
    out = classify_event(_p25_event(15001), client=client)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "talkgroup 15001" in prompt
    assert "TFD A2" in prompt
    assert out.talkgroup_id == 15001
    assert out.source == "p25"


def test_unknown_talkgroup_falls_back_gracefully():
    client = _FakeClient(ClassifyResponse(transmission_type=TransmissionType.UNKNOWN, confidence=0.2))
    classify_event(_p25_event(99999), client=client)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "unknown talkgroup" in prompt
