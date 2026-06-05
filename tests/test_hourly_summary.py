"""hourly_summary agent + /hourly-summary route tests (mocked Anthropic)."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.hourly_summary import HourlySummaryResponse, hourly_summary


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "events.db"))
    import db.database as dbm
    dbm._engine = None
    yield
    dbm._engine = None


def _seed_event(text, ttype, severity=None, minutes_ago=5):
    from db.database import TranscriptionEventRow, get_session
    with get_session() as s:
        s.add(TranscriptionEventRow(
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            frequency_mhz=154.37, raw_text=text, duration_sec=2.0,
            transmission_type=ttype, confidence=0.9, severity=severity,
        ))
        s.commit()


def test_hourly_summary_persists_rollup(temp_db):
    from db.queries import latest_hourly_summary

    _seed_event("structure fire on Speedway", "fire", severity="high")
    _seed_event("engine responding", "fire", severity="low")
    _seed_event("medical call", "ems", severity="medium")
    _seed_event("...static...", "unknown")  # excluded from counts

    client = FakeClient(HourlySummaryResponse(
        summary="A busy hour: a structure fire and routine EMS traffic.",
        top_incidents=["Structure fire on Speedway"],
    ))
    row_id = hourly_summary(window_min=60, client=client)
    assert client.messages.calls, "events present — the LLM should run"

    row = latest_hourly_summary()
    assert row.id == row_id
    assert row.event_count == 3  # the UNKNOWN event is not counted
    assert row.by_type == {"fire": 2, "ems": 1}
    assert row.severity_max == "high"
    assert "structure fire" in (row.summary or "").lower()
    assert row.top_incidents == ["Structure fire on Speedway"]


def test_hourly_summary_quiet_hour_skips_llm(temp_db):
    """No real voice events -> persist a cheap quiet-hour row, no LLM call."""
    from db.queries import latest_hourly_summary

    _seed_event("...noise...", "unknown")  # only noise present
    client = FakeClient(HourlySummaryResponse(summary="should not be used"))
    hourly_summary(window_min=60, client=client)

    assert client.messages.calls == [], "a quiet hour must not call the LLM"
    row = latest_hourly_summary()
    assert row.event_count == 0
    assert "quiet" in (row.summary or "").lower()


def test_hourly_summary_includes_gauge_and_weather_notes(temp_db):
    from db.queries import insert_gauge_reading, latest_hourly_summary
    from models.schemas import GaugeReading

    _seed_event("flood control checking the wash", "flood_control")
    insert_gauge_reading(GaugeReading(
        timestamp=datetime.now(timezone.utc), source="usgs", site_id="09486500",
        site_name="Santa Cruz River at Cortaro", discharge_cfs=120.0,
    ))
    client = FakeClient(HourlySummaryResponse(summary="Flood-control activity.", top_incidents=[]))
    hourly_summary(window_min=60, client=client)

    row = latest_hourly_summary()
    assert row.gauge_note and "120" in row.gauge_note


def test_hourly_routes_return_latest_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "events.db"))
    import db.database as dbm
    dbm._engine = None
    import api.deps as deps
    deps.get_readonly_engine.cache_clear()
    deps.get_settings.cache_clear()
    dbm.get_engine()

    from db.queries import insert_hourly_summary
    now = datetime.now(timezone.utc)
    insert_hourly_summary(
        window_start=now - timedelta(minutes=60), window_end=now,
        summary="An hour of routine traffic.", event_count=4,
        by_type={"fire": 3, "ems": 1}, top_incidents=["Brush fire"],
        severity_max="medium", gauge_note=None, weather_note=None,
    )

    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as client:
        latest = client.get("/hourly-summary").json()
        assert latest["summary"]["event_count"] == 4
        assert latest["summary"]["by_type"] == {"fire": 3, "ems": 1}
        history = client.get("/hourly-summaries", params={"limit": 10}).json()
        assert history["count"] == 1

    dbm._engine = None
    deps.get_readonly_engine.cache_clear()
    deps.get_settings.cache_clear()
