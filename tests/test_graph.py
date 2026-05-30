"""Smoke test: the LangGraph DAG runs end-to-end with mocked agent functions."""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    # Reset compiled graph too — it may close over module-level globals.
    import agents.graph as graph_module
    graph_module._compiled_graph = None
    yield db_file
    database_module._engine = None
    graph_module._compiled_graph = None


def test_graph_runs_end_to_end(temp_db, monkeypatch):
    from agents import graph as graph_module
    from db.queries import fetch_unclassified, insert_transcription, recent_transcriptions
    from models.schemas import (
        ClassifiedEvent,
        ExtractedEvent,
        Severity,
        TranscriptionEvent,
        TransmissionType,
    )

    row_id = insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370,
        raw_text="Med 843, respond code 2, TC unknown, 205 West Irvington Road",
        duration_sec=4.0,
    ))

    def fake_classify(event, **kwargs):
        return ClassifiedEvent(
            **event.model_dump(),
            transmission_type=TransmissionType.EMS,
            confidence=0.95,
        )

    def fake_extract(classified, **kwargs):
        return ExtractedEvent(
            **classified.model_dump(),
            locations=["205 W Irvington Rd"],
            incident_type="traffic collision",
            callsigns=["Med 843"],
            units=["Med 843"],
            status_codes=["code 2", "TC"],
            severity=Severity.MEDIUM,
            lat=32.18, lon=-111.00,
            wash_name=None,
            road_closure=False,
        )

    monkeypatch.setattr("agents.graph.classify_event", fake_classify)
    monkeypatch.setattr("agents.graph.extract_event", fake_extract)
    # Stub the Ntfy push — graph alert decision is MEDIUM so it shouldn't be called,
    # but if logic ever changes, the test still won't hit the network.
    monkeypatch.setattr("agents.graph.push_ntfy", lambda **kwargs: True)

    final = graph_module.run_for_row(row_id)

    # Graph populated all three result states.
    assert final["classified"].transmission_type is TransmissionType.EMS
    assert final["extracted"].units == ["Med 843"]
    assert final["alert"].should_alert is False  # MEDIUM severity = no alert

    # Row was updated in DB.
    row = recent_transcriptions(limit=1)[0]
    assert row.transmission_type == "ems"
    assert row.units == ["Med 843"]
    assert row.lat == 32.18

    # Row no longer appears in the unclassified backlog.
    assert fetch_unclassified() == []


def test_graph_alert_node_pushes_ntfy_on_high_severity(temp_db, monkeypatch):
    from agents import graph as graph_module
    from db.queries import insert_transcription
    from models.schemas import (
        ClassifiedEvent,
        ExtractedEvent,
        Severity,
        TranscriptionEvent,
        TransmissionType,
    )

    row_id = insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.370, raw_text="structure fire major", duration_sec=2.0,
    ))

    def fake_classify(event, **kwargs):
        return ClassifiedEvent(**event.model_dump(),
                               transmission_type=TransmissionType.FIRE, confidence=0.9)

    def fake_extract(classified, **kwargs):
        return ExtractedEvent(**classified.model_dump(),
                              severity=Severity.HIGH, road_closure=False)

    monkeypatch.setattr("agents.graph.classify_event", fake_classify)
    monkeypatch.setattr("agents.graph.extract_event", fake_extract)

    pushed = []

    def fake_push(title, body, **kwargs):
        pushed.append((title, body))
        return True

    monkeypatch.setattr("agents.graph.push_ntfy", fake_push)
    final = graph_module.run_for_row(row_id)

    assert final["alert"].should_alert is True
    assert len(pushed) == 1
    assert "alert" in pushed[0][0].lower() or "severity" in pushed[0][0].lower()
