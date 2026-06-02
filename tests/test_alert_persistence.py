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


def test_monsoon_digest_persists_no_alert_verdict_without_pushing(temp_db, monkeypatch):
    """A clean 'no flood' verdict is persisted (so /summary reflects it) but does
    NOT push or pollute the alert history."""
    from agents.alert import DigestResponse, monsoon_digest
    from db.database import TranscriptionEventRow, get_session
    from db.queries import latest_digest_alert, recent_alerts

    with get_session() as s:
        s.add(TranscriptionEventRow(
            timestamp=datetime.now(timezone.utc),
            frequency_mhz=154.37, raw_text="routine check", duration_sec=2.0,
            transmission_type="flood_control",
        ))
        s.commit()

    class FakeMessages:
        def create(self, **kwargs):
            return DigestResponse(should_alert=False, reason="all clear",
                                  summary="No active flash flood situation.")

    class FakeClient:
        messages = FakeMessages()

    pushes = []
    monkeypatch.setattr("agents.alert.push_ntfy", lambda **kw: pushes.append(kw) or True)

    decision = monsoon_digest(client=FakeClient())
    assert decision.should_alert is False
    assert pushes == []  # no push on a clean verdict

    latest = latest_digest_alert()
    assert latest is not None and latest.should_alert is False
    assert "No active" in (latest.summary or "")
    # The non-alert verdict must not show up in the alert history.
    assert recent_alerts(source="monsoon_digest") == []


def test_monsoon_digest_persists_no_activity_verdict(temp_db):
    """Even the no-data short-circuit is persisted, so the dashboard shows a
    fresh 'quiet' verdict instead of a stale alert."""
    from agents.alert import monsoon_digest
    from db.queries import latest_digest_alert

    decision = monsoon_digest()  # nothing seeded → no-recent-activity branch
    assert decision.should_alert is False
    assert decision.reason == "no recent activity"

    latest = latest_digest_alert()
    assert latest is not None and latest.should_alert is False


def test_format_gauges_marks_baseflow_reach():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from agents.alert import _MONSOON_PROMPT, _format_gauges
    from config.gauges import site_is_baseflow

    assert site_is_baseflow("09486500") is True   # Santa Cruz @ Cortaro (effluent)
    assert site_is_baseflow("09485700") is False  # Rillito @ Dodge

    cortaro = SimpleNamespace(
        timestamp=datetime(2026, 6, 1, 2, 45, tzinfo=timezone.utc),
        discharge_cfs=45.0, gage_height_ft=8.33, precip_in=None,
        site_id="09486500", site_name="Santa Cruz River at Cortaro", source="usgs",
    )
    out = _format_gauges([cortaro])
    assert "[baseflow]" in out and "Cortaro" in out
    # The prompt explains what [baseflow] means.
    assert "baseflow" in _MONSOON_PROMPT.lower()


def test_monsoon_digest_feeds_active_weather_alert_to_prompt(temp_db, monkeypatch):
    """An active NWS alert alone triggers the LLM path and reaches the prompt."""
    from datetime import timedelta

    from agents.alert import DigestResponse, monsoon_digest
    from db.queries import insert_weather_alert
    from models.schemas import WeatherAlert

    now = datetime.now(timezone.utc)
    insert_weather_alert(WeatherAlert(
        alert_id="ffw1", event="Flash Flood Warning",
        headline="Flash Flood Warning for eastern Pima County",
        severity="Severe", expires=now + timedelta(hours=2), fetched_at=now,
    ))

    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return DigestResponse(should_alert=True, summary="FFW active", reason="nws")

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr("agents.alert.push_ntfy", lambda **kw: True)

    decision = monsoon_digest(client=FakeClient())
    assert "Flash Flood Warning" in captured["prompt"]
    assert decision.should_alert is True
