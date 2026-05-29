"""classify_event tests with a fake instructor client (no Anthropic calls)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from agents.classify import ClassifyResponse, classify_event
from models.schemas import TranscriptionEvent, TransmissionType


class FakeMessages:
    """Stand-in for client.messages — records the call, returns canned response."""

    def __init__(self, response: ClassifyResponse):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        # Honor the response_model contract — return an instance of it.
        return self.response


class FakeClient:
    def __init__(self, response: ClassifyResponse):
        self.messages = FakeMessages(response)


def _event(text: str = "Med 843, respond code 2", freq: float = 154.370) -> TranscriptionEvent:
    return TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=freq,
        raw_text=text,
        duration_sec=3.0,
    )


def test_classify_returns_classified_event_with_response_fields():
    fake_response = ClassifyResponse(
        transmission_type=TransmissionType.EMS, confidence=0.93, language="en"
    )
    client = FakeClient(fake_response)
    out = classify_event(_event(), client=client)
    assert out.transmission_type is TransmissionType.EMS
    assert out.confidence == 0.93
    assert out.raw_text == "Med 843, respond code 2"
    # Original TranscriptionEvent fields preserved.
    assert out.frequency_mhz == 154.370


def test_classify_prompt_includes_frequency_hint():
    """The classifier prompt must mention the channel context — strong prior."""
    fake_response = ClassifyResponse(
        transmission_type=TransmissionType.FIRE, confidence=0.8, language="en"
    )
    client = FakeClient(fake_response)
    classify_event(_event(freq=154.370), client=client)
    call = client.messages.calls[0]
    prompt = call["messages"][0]["content"]
    assert "154.37" in prompt
    assert "Rural Metro" in prompt
    assert call["response_model"] is ClassifyResponse


def test_classify_uses_configured_model():
    fake_response = ClassifyResponse(
        transmission_type=TransmissionType.WEATHER, confidence=0.99, language="en"
    )
    client = FakeClient(fake_response)
    classify_event(_event(), client=client, model="claude-haiku-4-5-20251001")
    assert client.messages.calls[0]["model"] == "claude-haiku-4-5-20251001"
