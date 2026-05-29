from datetime import datetime, timezone

from models.schemas import (
    APRSEvent,
    AlertDecision,
    ClassifiedEvent,
    ExtractedEvent,
    Severity,
    TranscriptionEvent,
    TransmissionType,
)


def test_transcription_event_minimal():
    e = TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="engine 31 respond",
        duration_sec=4.2,
    )
    assert e.source == "analog"
    assert e.talkgroup_id is None


def test_classified_event_inherits_fields():
    e = ClassifiedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="engine 31 respond",
        duration_sec=4.2,
        transmission_type=TransmissionType.FIRE,
        confidence=0.92,
    )
    assert e.language == "en"
    assert e.transmission_type is TransmissionType.FIRE


def test_extracted_event_defaults():
    e = ExtractedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="rillito wash flooded at first ave",
        duration_sec=3.0,
        transmission_type=TransmissionType.FLOOD_CONTROL,
        confidence=0.8,
    )
    assert e.severity is Severity.UNKNOWN
    assert e.locations == []
    assert e.callsigns == []


def test_aprs_event_minimal():
    e = APRSEvent(timestamp=datetime.now(timezone.utc), callsign="N7XYZ-9")
    assert e.source == "aprs"
    assert e.lat is None


def test_alert_decision_defaults():
    d = AlertDecision(should_alert=True, reason="severity high")
    assert d.correlated_event_ids == []
