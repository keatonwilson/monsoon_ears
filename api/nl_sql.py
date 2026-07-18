"""Natural language → SQL pipeline.

User question → Haiku 4.5 (structured output) → candidate SELECT → sqlglot
validation → read-only SQLite execution with a wall-clock timeout. Every
failure path returns a `NLSQLError` with a human-readable reason that the
dashboard surfaces inline so the user can iterate.

Validation rules:
  * exactly one top-level statement
  * top-level node is a SELECT
  * referenced tables ⊆ {transcription_events, aprs_events, alerts}
  * no DDL/DML/PRAGMA/ATTACH expressions anywhere in the parse tree
  * any existing LIMIT is replaced with `LIMIT 200`
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import sqlglot
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlglot import exp

from agents.caching import cached_system

logger = logging.getLogger(__name__)


ALLOWED_TABLES = {"transcription_events", "aprs_events", "alerts"}
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Pragma, exp.Attach, exp.Detach, exp.Merge,
)
HARD_LIMIT = 200
DEFAULT_TIMEOUT_SEC = 5.0


SCHEMA_DOC = """\
You have access to a SQLite database with three read-only tables. Generate
exactly one SELECT statement that answers the user's question. Use only
columns listed below; do not invent columns. Prefer explicit column names
over `SELECT *`.

Table `transcription_events` — one row per Whisper-transcribed radio chunk:
  id INTEGER PRIMARY KEY, timestamp DATETIME, frequency_mhz REAL,
  raw_text TEXT, duration_sec REAL,
  source TEXT,            -- 'analog' | 'p25'
  talkgroup_id INTEGER,
  transmission_type TEXT, -- 'fire' | 'ems' | 'police' | 'ham' | 'weather'
                          -- | 'aprs' | 'flood_control' | 'unknown'
  confidence REAL, language TEXT,
  locations TEXT,         -- JSON array of strings
  incident_type TEXT,
  callsigns TEXT, units TEXT, status_codes TEXT,  -- all JSON arrays
  severity TEXT,          -- 'low' | 'medium' | 'high' | 'unknown'
  lat REAL, lon REAL,
  wash_name TEXT, road_closure INTEGER

Table `aprs_events` — one row per APRS-IS packet near Tucson:
  id INTEGER PRIMARY KEY, timestamp DATETIME, callsign TEXT,
  lat REAL, lon REAL, symbol TEXT, comment TEXT,
  temp_f REAL, rainfall_in REAL, wind_mph REAL,
  source TEXT             -- always 'aprs'

Table `alerts` — one row per persisted alert:
  id INTEGER PRIMARY KEY, timestamp DATETIME,
  source TEXT,            -- 'rule' | 'monsoon_digest'
  transcription_id INTEGER, should_alert INTEGER,
  reason TEXT, summary TEXT, correlation_note TEXT,
  correlated_event_ids TEXT  -- JSON array

Rules:
  * Use SQLite functions (e.g. datetime('now', '-1 hour')) for time math.
  * Do not use PRAGMA, ATTACH, INSERT, UPDATE, DELETE, or DDL.
  * Limit results to 200 rows or fewer.
"""


class NLQueryResponse(BaseModel):
    """Forced shape of the model's reply — just the SQL string, nothing else."""
    sql: str


class NLSQLError(Exception):
    """Raised when the candidate SQL fails validation or execution."""


@dataclass
class NLSQLResult:
    sql: str
    rows: list[dict[str, Any]]
    row_count: int


# --- Validation --------------------------------------------------------------


def validate_select(candidate: str) -> str:
    """Parse and check `candidate`. Returns the rewritten SQL (with LIMIT 200)."""
    candidate = candidate.strip().rstrip(";")
    if not candidate:
        raise NLSQLError("model returned an empty query")

    try:
        parsed = sqlglot.parse(candidate, dialect="sqlite")
    except sqlglot.errors.ParseError as exc:
        raise NLSQLError(f"could not parse SQL: {exc}") from exc

    if len(parsed) != 1:
        raise NLSQLError(f"expected exactly one statement, got {len(parsed)}")
    stmt = parsed[0]
    if stmt is None:
        raise NLSQLError("parsed to an empty statement")
    if not isinstance(stmt, exp.Select):
        raise NLSQLError(f"only SELECT statements are allowed (got {type(stmt).__name__})")

    for node in stmt.walk():
        # sqlglot.walk yields tuples in some versions; normalize.
        target = node[0] if isinstance(node, tuple) else node
        if isinstance(target, FORBIDDEN_NODES):
            raise NLSQLError(f"forbidden expression: {type(target).__name__}")

    referenced = {
        t.name for t in stmt.find_all(exp.Table) if t.name
    }
    extra = referenced - ALLOWED_TABLES
    if extra:
        raise NLSQLError(
            f"references disallowed tables: {sorted(extra)}; "
            f"allowed: {sorted(ALLOWED_TABLES)}"
        )

    # Enforce LIMIT 200 — replace any existing one.
    stmt.set("limit", exp.Limit(expression=exp.Literal.number(HARD_LIMIT)))
    return stmt.sql(dialect="sqlite")


# --- Anthropic client (lazy, mockable) ---------------------------------------


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        import instructor
        _client = instructor.from_anthropic(anthropic.Anthropic())
    return _client


def _build_prompt(question: str) -> str:
    return f"User question: {question}\n\nReturn only the SQL."


def generate_sql(
    question: str,
    client=None,
    model: Optional[str] = None,
) -> str:
    """Ask Haiku for a candidate SELECT. Does not validate or execute."""
    model_name = model or os.getenv("NL_SQL_MODEL") or os.getenv("CLASSIFY_MODEL", "claude-haiku-4-5-20251001")
    try:
        client = client if client is not None else _get_client()
        response = client.messages.create(
            model=model_name,
            max_tokens=512,
            # The schema doc is identical on every question, so it rides in a cached
            # system block (default 5-min TTL fits the bursty, interactive cadence).
            system=cached_system(SCHEMA_DOC),
            messages=[{"role": "user", "content": _build_prompt(question)}],
            response_model=NLQueryResponse,
        )
    except Exception as exc:  # noqa: BLE001 — anthropic/instructor errors, network, etc.
        raise NLSQLError(f"couldn't generate SQL: {exc}") from exc
    return response.sql


# --- Execution ---------------------------------------------------------------


def execute_validated(engine: Engine, sql: str, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> list[dict[str, Any]]:
    """Run `sql` on the read-only engine. Returns list of dicts."""
    with engine.connect() as conn:
        raw = conn.connection
        try:
            raw.execute(f"SELECT 1")  # sanity warm-up
        except Exception:
            pass
        # SQLite per-connection statement timeout via progress_handler:
        # called every N ops; if it returns truthy, the query is interrupted.
        import time as _time
        started = _time.monotonic()

        def _watchdog() -> int:
            return 1 if (_time.monotonic() - started) > timeout_sec else 0

        try:
            raw.set_progress_handler(_watchdog, 10_000)
        except Exception:  # noqa: BLE001 — older sqlite may not support
            pass

        try:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, r)) for r in result.fetchall()]
        finally:
            try:
                raw.set_progress_handler(None, 0)
            except Exception:  # noqa: BLE001
                pass
        return rows


def run(
    question: str,
    engine: Engine,
    client=None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> NLSQLResult:
    """Full pipeline: question → SQL → validate → execute → rows."""
    candidate = generate_sql(question, client=client)
    validated = validate_select(candidate)
    logger.info("nl_sql: %r -> %s", question, validated)
    try:
        rows = execute_validated(engine, validated, timeout_sec=timeout_sec)
    except DBAPIError as exc:
        # sqlglot's parser accepts SQL that isn't valid SQLite at runtime (e.g.
        # non-SQLite date/interval syntax) — surface it as a query rejection
        # rather than an unhandled 500.
        raise NLSQLError(f"query failed to execute: {exc.orig}") from exc
    return NLSQLResult(sql=validated, rows=rows, row_count=len(rows))
