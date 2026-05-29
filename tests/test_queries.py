"""Round-trip tests for the Phase 03 db.queries helpers against a temp SQLite."""

from datetime import datetime, timedelta, timezone

import pytest

from models.schemas import (
    APRSEvent,
    ClassifiedEvent,
    ExtractedEvent,
    Severity,
    TranscriptionEvent,
    TransmissionType,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a per-test SQLite file and reset the engine cache."""
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    # db.database caches the engine module-level; force-reimport for isolation.
    import db.database as database_module
    database_module._engine = None
    yield db_file
    database_module._engine = None


def _make_event(text: str = "engine 31 respond") -> TranscriptionEvent:
    return TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text=text,
        duration_sec=3.5,
    )


def test_insert_and_fetch_unclassified(temp_db):
    from db.queries import fetch_unclassified, insert_transcription

    id1 = insert_transcription(_make_event("first"))
    id2 = insert_transcription(_make_event("second"))
    pending = fetch_unclassified(limit=10)
    assert {r.id for r in pending} == {id1, id2}
    assert all(r.transmission_type is None for r in pending)


def test_update_classification_clears_pending(temp_db):
    from db.queries import fetch_unclassified, insert_transcription, update_classification

    row_id = insert_transcription(_make_event())
    classified = ClassifiedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="x",
        duration_sec=1.0,
        transmission_type=TransmissionType.EMS,
        confidence=0.91,
    )
    update_classification(row_id, classified)
    assert fetch_unclassified() == []  # no longer pending


def test_update_extraction_persists_lists(temp_db):
    from db.queries import insert_transcription, recent_transcriptions, update_extraction

    row_id = insert_transcription(_make_event())
    extracted = ExtractedEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="x",
        duration_sec=1.0,
        transmission_type=TransmissionType.EMS,
        confidence=0.91,
        locations=["205 W Irvington Rd"],
        callsigns=["Med 843"],
        units=["Med 843"],
        status_codes=["code 2"],
        severity=Severity.HIGH,
        wash_name=None,
        road_closure=False,
    )
    update_extraction(row_id, extracted)
    row = recent_transcriptions(limit=1)[0]
    assert row.locations == ["205 W Irvington Rd"]
    assert row.callsigns == ["Med 843"]
    assert row.severity == "high"


def test_recent_flood_events_filters_by_type_and_time(temp_db):
    from db.database import TranscriptionEventRow, get_session
    from db.queries import recent_flood_events

    now = datetime.now(timezone.utc)
    # In-window EMS, in-window HAM (excluded by type), out-of-window EMS.
    with get_session() as s:
        s.add(TranscriptionEventRow(timestamp=now - timedelta(minutes=5),
                                    frequency_mhz=154.37, raw_text="a",
                                    duration_sec=1.0, transmission_type="ems"))
        s.add(TranscriptionEventRow(timestamp=now - timedelta(minutes=10),
                                    frequency_mhz=146.82, raw_text="b",
                                    duration_sec=1.0, transmission_type="ham"))
        s.add(TranscriptionEventRow(timestamp=now - timedelta(minutes=120),
                                    frequency_mhz=154.37, raw_text="c",
                                    duration_sec=1.0, transmission_type="ems"))
        s.commit()

    found = recent_flood_events(minutes=60)
    texts = {r.raw_text for r in found}
    assert texts == {"a"}  # only the in-window EMS


def test_recent_aprs_filters_by_time(temp_db):
    from db.queries import insert_aprs, recent_aprs

    now = datetime.now(timezone.utc)
    insert_aprs(APRSEvent(timestamp=now - timedelta(minutes=5),
                          callsign="N7XYZ-9", temp_f=85.0))
    insert_aprs(APRSEvent(timestamp=now - timedelta(minutes=45),
                          callsign="W1OLD-1", temp_f=82.0))
    found = recent_aprs(minutes=30)
    assert {r.callsign for r in found} == {"N7XYZ-9"}
