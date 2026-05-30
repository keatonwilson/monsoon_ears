"""Verify that alert decisions are persisted to the alerts table."""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    import agents.graph as graph_module
    graph_module._compiled_graph = None
    yield db_file
    database_module._engine = None
    graph_module._compiled_graph = None


def test_alert_node_writes_alerts_row_on_high_severity(temp_db, monkeypatch):
    from agents import graph as graph_module
    from db.queries import insert_transcription, recent_alerts
    from models.schemas import (
        ClassifiedEvent,
        ExtractedEvent,
        Severity,
        TranscriptionEvent,
        TransmissionType,
    )

    row_id = insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370, raw_text="Engine 4 respond to structure fire at 5502 East 22nd Street", duration_sec=2.0,
    ))

    def fake_classify(event, **kwargs):
        return ClassifiedEvent(**event.model_dump(),
                               transmission_type=TransmissionType.FIRE, confidence=0.9)

    def fake_extract(classified, **kwargs):
        return ExtractedEvent(**classified.model_dump(),
                              severity=Severity.HIGH, road_closure=False)

    monkeypatch.setattr("agents.graph.classify_event", fake_classify)
    monkeypatch.setattr("agents.graph.extract_event", fake_extract)
    monkeypatch.setattr("agents.graph.push_ntfy", lambda **kwargs: True)

    graph_module.run_for_row(row_id)

    alerts = recent_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0].source == "rule"
    assert alerts[0].transcription_id == row_id
    assert alerts[0].should_alert is True
    assert "severity" in (alerts[0].reason or "").lower()


def test_alert_node_does_not_write_for_low_severity(temp_db, monkeypatch):
    from agents import graph as graph_module
    from db.queries import insert_transcription, recent_alerts
    from models.schemas import (
        ClassifiedEvent,
        ExtractedEvent,
        Severity,
        TranscriptionEvent,
        TransmissionType,
    )

    row_id = insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370, raw_text="routine traffic", duration_sec=2.0,
    ))

    monkeypatch.setattr(
        "agents.graph.classify_event",
        lambda event, **kwargs: ClassifiedEvent(
            **event.model_dump(), transmission_type=TransmissionType.EMS, confidence=0.9
        ),
    )
    monkeypatch.setattr(
        "agents.graph.extract_event",
        lambda c, **kwargs: ExtractedEvent(
            **c.model_dump(), severity=Severity.LOW, road_closure=False
        ),
    )
    monkeypatch.setattr("agents.graph.push_ntfy", lambda **kwargs: True)

    graph_module.run_for_row(row_id)
    assert recent_alerts() == []


def test_monsoon_digest_persists_alert_when_should_alert(temp_db, monkeypatch):
    from agents.alert import DigestResponse, monsoon_digest
    from db.database import TranscriptionEventRow, get_session
    from db.queries import latest_digest_alert

    # Seed at least one flood-control row so digest doesn't short-circuit.
    with get_session() as s:
        s.add(TranscriptionEventRow(
            timestamp=datetime.now(timezone.utc),
            frequency_mhz=154.37, raw_text="rillito wash flooded",
            duration_sec=3.0, transmission_type="flood_control",
        ))
        s.commit()

    class FakeMessages:
        def create(self, **kwargs):
            return DigestResponse(
                should_alert=True,
                summary="Active flash flood near Rillito",
                correlation_note="0.8in/hr at NE8U correlates with wash dispatch",
                reason="monsoon correlation",
                correlated_event_ids=[1],
            )

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr("agents.alert.push_ntfy", lambda **kwargs: True)

    decision = monsoon_digest(client=FakeClient())
    assert decision.should_alert is True

    persisted = latest_digest_alert()
    assert persisted is not None
    assert persisted.source == "monsoon_digest"
    assert persisted.summary and "Rillito" in persisted.summary
    assert persisted.correlated_event_ids == [1]
