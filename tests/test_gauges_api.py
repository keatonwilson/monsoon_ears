"""GET /gauges endpoint test (TestClient + per-test SQLite)."""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    import api.deps as deps_module
    deps_module.get_readonly_engine.cache_clear()
    deps_module.get_settings.cache_clear()
    database_module.get_engine()

    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as client:
        yield client

    database_module._engine = None
    deps_module.get_readonly_engine.cache_clear()
    deps_module.get_settings.cache_clear()


def _seed_gauge(**kwargs):
    from db.queries import insert_gauge_reading
    from models.schemas import GaugeReading
    base = dict(
        timestamp=datetime.now(timezone.utc),
        source="usgs",
        site_id="09485700",
        site_name="Rillito Creek at Dodge Blvd",
        discharge_cfs=120.0,
        gage_height_ft=4.2,
    )
    base.update(kwargs)
    return insert_gauge_reading(GaugeReading(**base))


def test_gauges_empty(api_client):
    r = api_client.get("/gauges")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "results": []}


def test_gauges_returns_seeded_reading_with_wash_label(api_client):
    _seed_gauge()
    r = api_client.get("/gauges", params={"minutes": 120})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    row = body["results"][0]
    assert row["site_id"] == "09485700"
    assert row["discharge_cfs"] == 120.0
    assert row["wash"] == "Rillito"  # derived from config/gauges.py catalog
    assert row["source"] == "usgs"
