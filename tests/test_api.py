"""End-to-end tests for the FastAPI app (TestClient + per-test SQLite)."""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    # Reset the caches that hold engines + settings.
    import db.database as database_module
    database_module._engine = None
    import api.deps as deps_module
    deps_module.get_readonly_engine.cache_clear()
    deps_module.get_settings.cache_clear()

    # Touch the DB by calling get_engine so the read-only engine has a file to open.
    database_module.get_engine()

    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as client:
        yield client

    database_module._engine = None
    deps_module.get_readonly_engine.cache_clear()
    deps_module.get_settings.cache_clear()


def _seed_transcription(text="dispatch", freq=154.37, **classified):
    from db.queries import insert_transcription
    from models.schemas import TranscriptionEvent
    return insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=freq, raw_text=text, duration_sec=2.0,
    ))


def _seed_aprs(callsign="N7XYZ-13", **kwargs):
    from db.queries import insert_aprs
    from models.schemas import APRSEvent
    return insert_aprs(APRSEvent(
        timestamp=datetime.now(timezone.utc),
        callsign=callsign, **kwargs,
    ))


def _seed_alert(source="rule", reason="severity=HIGH", correlated_event_ids=None):
    from db.queries import insert_alert
    from models.schemas import AlertDecision
    return insert_alert(
        source=source,
        decision=AlertDecision(
            should_alert=True, reason=reason, summary="x",
            correlated_event_ids=correlated_event_ids or [],
        ),
    )


# --- /health -----------------------------------------------------------------


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --- /events -----------------------------------------------------------------


def test_events_empty(api_client):
    r = api_client.get("/events")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "results": []}


def test_events_returns_rows_newest_first(api_client):
    id1 = _seed_transcription("first")
    id2 = _seed_transcription("second")
    r = api_client.get("/events?limit=5")
    body = r.json()
    assert body["count"] == 2
    assert body["results"][0]["id"] == id2
    assert body["results"][1]["id"] == id1


def test_event_by_id_404(api_client):
    r = api_client.get("/events/9999")
    assert r.status_code == 404


def test_event_by_id_ok(api_client):
    eid = _seed_transcription("rural metro")
    r = api_client.get(f"/events/{eid}")
    assert r.status_code == 200
    assert r.json()["raw_text"] == "rural metro"


# --- /aprs -------------------------------------------------------------------


def test_aprs_returns_rows(api_client):
    _seed_aprs(callsign="NE8U", temp_f=89.0)
    _seed_aprs(callsign="N7WSS", rainfall_in=0.2)
    r = api_client.get("/aprs")
    body = r.json()
    assert body["count"] == 2
    callsigns = {row["callsign"] for row in body["results"]}
    assert callsigns == {"NE8U", "N7WSS"}


# --- /summary ----------------------------------------------------------------


def test_summary_empty(api_client):
    r = api_client.get("/summary")
    body = r.json()
    assert body["available"] is False
    assert body["summary"] is None


def test_summary_returns_latest_digest_alert(api_client):
    _seed_alert(source="rule", reason="severity=HIGH")
    _seed_alert(source="monsoon_digest", reason="monsoon", correlated_event_ids=[1, 2])
    r = api_client.get("/summary")
    body = r.json()
    assert body["available"] is True
    assert body["reason"] == "monsoon"
    assert body["correlated_event_ids"] == [1, 2]


# --- /alerts -----------------------------------------------------------------


def test_alerts_filterable_by_source(api_client):
    _seed_alert(source="rule")
    _seed_alert(source="monsoon_digest")
    r = api_client.get("/alerts?source=monsoon_digest")
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["source"] == "monsoon_digest"


# --- /threads ----------------------------------------------------------------


def _seed_thread(n: int = 3, freq: float = 154.37):
    """Seed a freshly-clustered thread on `freq`."""
    from datetime import timedelta
    from db.queries import insert_transcription
    from models.schemas import TranscriptionEvent
    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    for i in range(n):
        insert_transcription(TranscriptionEvent(
            timestamp=base + timedelta(seconds=15 * i),
            frequency_mhz=freq, raw_text=f"frag {i}", duration_sec=2.0,
        ))


def test_threads_empty(api_client):
    r = api_client.get("/threads")
    assert r.json() == {"count": 0, "results": []}


def test_threads_returns_cluster(api_client):
    _seed_thread(n=3)
    r = api_client.get("/threads")
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["event_count"] == 3
    assert body["results"][0]["frequency_mhz"] == 154.37


def test_thread_by_id_includes_events(api_client):
    _seed_thread(n=2)
    r = api_client.get("/threads")
    thread_id = r.json()["results"][0]["id"]
    detail = api_client.get(f"/threads/{thread_id}").json()
    assert len(detail["events"]) == 2
    assert detail["events"][0]["raw_text"] == "frag 0"


def test_thread_404(api_client):
    assert api_client.get("/threads/9999").status_code == 404
    assert api_client.post("/threads/9999/summarize").status_code == 404
