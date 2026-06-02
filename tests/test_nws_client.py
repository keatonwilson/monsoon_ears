"""NWS alerts client parsing + dedup/active queries."""

from datetime import datetime, timedelta, timezone

import pytest

from ingestion.nws_client import parse_nws_alerts


def _feature(**props):
    base = {
        "id": "urn:oid:flood-1",
        "event": "Flash Flood Warning",
        "severity": "Severe",
        "certainty": "Likely",
        "urgency": "Immediate",
        "headline": "Flash Flood Warning until 6 PM MST",
        "areaDesc": "Pima, AZ",
        "status": "Actual",
        "messageType": "Alert",
        "onset": "2026-07-15T15:00:00-07:00",
        "expires": "2026-07-15T18:00:00-07:00",
        "sent": "2026-07-15T15:00:00-07:00",
    }
    base.update(props)
    return {"properties": base}


def test_parse_extracts_fields_and_utc():
    alerts = parse_nws_alerts({"features": [_feature()]})
    assert len(alerts) == 1
    a = alerts[0]
    assert a.event == "Flash Flood Warning"
    assert a.severity == "Severe"
    assert a.expires.tzinfo is not None and a.expires.utcoffset() == timedelta(0)


def test_parse_skips_test_and_cancel():
    payload = {"features": [
        _feature(id="t1", status="Test"),
        _feature(id="c1", messageType="Cancel"),
        _feature(id="ok1"),
    ]}
    alerts = parse_nws_alerts(payload)
    assert [a.alert_id for a in alerts] == ["ok1"]


def test_parse_skips_missing_event_or_id():
    payload = {"features": [
        {"properties": {"id": "x", "severity": "Severe"}},   # no event
        {"properties": {"event": "Heat Advisory"}},          # no id
    ]}
    assert parse_nws_alerts(payload) == []


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "events.db"))
    import db.database as dbm
    dbm._engine = None
    yield
    dbm._engine = None


def test_insert_dedupes_and_active_filters_expired(temp_db):
    from db.queries import active_weather_alerts, insert_weather_alert
    from models.schemas import WeatherAlert

    now = datetime.now(timezone.utc)
    live = WeatherAlert(alert_id="a-live", event="Flash Flood Warning",
                        expires=now + timedelta(hours=2), fetched_at=now)
    stale = WeatherAlert(alert_id="a-stale", event="Flood Watch",
                         expires=now - timedelta(hours=1), fetched_at=now)

    assert insert_weather_alert(live) is not None
    assert insert_weather_alert(live) is None   # dedup by alert_id
    assert insert_weather_alert(stale) is not None

    active = active_weather_alerts(now=now)
    ids = {a.alert_id for a in active}
    assert "a-live" in ids and "a-stale" not in ids
