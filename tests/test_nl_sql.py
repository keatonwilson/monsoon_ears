"""NL→SQL pipeline: validator + executor + /query endpoint with mocked Haiku."""

from datetime import datetime, timezone

import pytest

from api.nl_sql import NLQueryResponse, NLSQLError, validate_select


# --- validator ---------------------------------------------------------------


def test_validator_accepts_simple_select():
    out = validate_select("SELECT id, raw_text FROM transcription_events")
    assert "SELECT" in out
    assert "LIMIT 200" in out.upper()


def test_validator_replaces_existing_limit_with_hard_limit():
    out = validate_select("SELECT id FROM transcription_events LIMIT 1000")
    assert "LIMIT 1000" not in out
    assert "LIMIT 200" in out.upper()


def test_validator_rejects_drop():
    with pytest.raises(NLSQLError, match="only SELECT"):
        validate_select("DROP TABLE transcription_events")


def test_validator_rejects_insert():
    with pytest.raises(NLSQLError, match="only SELECT"):
        validate_select("INSERT INTO alerts (reason) VALUES ('x')")


def test_validator_rejects_update():
    with pytest.raises(NLSQLError, match="only SELECT"):
        validate_select("UPDATE transcription_events SET raw_text='x'")


def test_validator_rejects_unknown_table():
    with pytest.raises(NLSQLError, match="disallowed tables"):
        validate_select("SELECT * FROM sqlite_master")


def test_validator_rejects_pragma():
    with pytest.raises(NLSQLError):
        validate_select("PRAGMA table_info(transcription_events)")


def test_validator_rejects_multi_statement():
    with pytest.raises(NLSQLError, match="exactly one statement"):
        validate_select("SELECT 1; SELECT 2")


def test_validator_accepts_join_within_allowed_tables():
    sql = "SELECT t.id, a.reason FROM transcription_events t JOIN alerts a ON a.transcription_id = t.id"
    out = validate_select(sql)
    assert "JOIN alerts" in out


# --- /query endpoint integration --------------------------------------------


class FakeMessages:
    def __init__(self, sql: str):
        self.sql = sql

    def create(self, **kwargs):
        return NLQueryResponse(sql=self.sql)


class FakeClient:
    def __init__(self, sql: str):
        self.messages = FakeMessages(sql)


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


def _seed(text="cardiac call"):
    from db.queries import insert_transcription
    from models.schemas import TranscriptionEvent
    return insert_transcription(TranscriptionEvent(
        timestamp=datetime.now(timezone.utc),
        frequency_mhz=154.37, raw_text=text, duration_sec=2.0,
    ))


def test_query_happy_path(api_client, monkeypatch):
    _seed("cardiac call")
    _seed("structure fire")
    fake_sql = "SELECT id, raw_text FROM transcription_events"
    monkeypatch.setattr("api.nl_sql._get_client", lambda: FakeClient(fake_sql))
    r = api_client.post("/query", json={"question": "show me everything"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_count"] == 2
    assert "LIMIT 200" in body["sql"].upper()
    assert {row["raw_text"] for row in body["rows"]} == {"cardiac call", "structure fire"}


def test_query_rejects_dangerous_sql(api_client, monkeypatch):
    monkeypatch.setattr(
        "api.nl_sql._get_client",
        lambda: FakeClient("DROP TABLE transcription_events"),
    )
    r = api_client.post("/query", json={"question": "wipe everything"})
    assert r.status_code == 400
    assert "SELECT" in r.json()["detail"]


def test_query_rejects_disallowed_table(api_client, monkeypatch):
    monkeypatch.setattr(
        "api.nl_sql._get_client",
        lambda: FakeClient("SELECT name FROM sqlite_master"),
    )
    r = api_client.post("/query", json={"question": "list tables"})
    assert r.status_code == 400
    assert "disallowed" in r.json()["detail"].lower()


def test_query_short_circuits_on_empty_question(api_client):
    r = api_client.post("/query", json={"question": "hi"})
    assert r.status_code == 422  # Pydantic min_length=3
