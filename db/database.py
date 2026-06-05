import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import JSON, Column, event
from sqlmodel import Field, Session, SQLModel, create_engine


class TranscriptionEventRow(SQLModel, table=True):
    __tablename__ = "transcription_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    frequency_mhz: float
    raw_text: str
    duration_sec: float
    source: str = Field(default="analog", index=True)
    talkgroup_id: Optional[int] = Field(default=None, index=True)

    # Phase 03 (classification) — nullable now so no migration needed later.
    transmission_type: Optional[str] = None
    confidence: Optional[float] = None
    language: Optional[str] = None

    # Phase 03 (extraction)
    locations: Optional[list] = Field(default=None, sa_column=Column(JSON))
    incident_type: Optional[str] = None
    callsigns: Optional[list] = Field(default=None, sa_column=Column(JSON))
    units: Optional[list] = Field(default=None, sa_column=Column(JSON))
    status_codes: Optional[list] = Field(default=None, sa_column=Column(JSON))
    severity: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    wash_name: Optional[str] = None
    road_closure: Optional[bool] = None
    # Phase: accuracy — transcript with garbled local proper nouns repaired by
    # the extract LLM against the Tucson gazetteer. Null = clean or unintelligible.
    corrected_text: Optional[str] = None


class APRSEventRow(SQLModel, table=True):
    __tablename__ = "aprs_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    callsign: str = Field(index=True)
    lat: Optional[float] = None
    lon: Optional[float] = None
    symbol: Optional[str] = None
    comment: Optional[str] = None
    temp_f: Optional[float] = None
    rainfall_in: Optional[float] = None
    wind_mph: Optional[float] = None
    source: str = "aprs"


class GaugeReadingRow(SQLModel, table=True):
    """Stream/rain gauge reading from USGS or Pima County ALERT. Feeds the
    monsoon correlation digest alongside voice + APRS weather."""
    __tablename__ = "gauge_readings"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    source: str = Field(default="usgs", index=True)  # "usgs" | "pima_alert"
    site_id: str = Field(index=True)
    site_name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    discharge_cfs: Optional[float] = None
    gage_height_ft: Optional[float] = None
    precip_in: Optional[float] = None


class EventThreadRow(SQLModel, table=True):
    """A cluster of related transcription events on the same frequency.

    Events whose timestamps are within `THREAD_GAP_SEC` of each other on the
    same frequency are stitched into a thread. A summary agent rolls the
    cluster up into a coherent narrative so the dashboard doesn't have to
    show every key-up as its own row.
    """
    __tablename__ = "event_threads"

    id: Optional[int] = Field(default=None, primary_key=True)
    frequency_mhz: float = Field(index=True)
    # `source`/`talkgroup_id` mirror the constituent events so the dashboard can
    # label a thread by its leg. P25 threads are clustered by talkgroup (every
    # P25 event shares frequency_mhz=0.0, so frequency alone would merge every
    # talkgroup into one thread); analog threads cluster by frequency.
    source: str = Field(default="analog", index=True)
    talkgroup_id: Optional[int] = Field(default=None, index=True)
    start_timestamp: datetime = Field(index=True)
    end_timestamp: datetime = Field(index=True)
    event_count: int = 0
    event_ids: Optional[list] = Field(default=None, sa_column=Column(JSON))
    # Summary fields — populated by agents/summarize.py.
    summary: Optional[str] = None
    transmission_type: Optional[str] = None
    severity: Optional[str] = None
    locations: Optional[list] = Field(default=None, sa_column=Column(JSON))
    units: Optional[list] = Field(default=None, sa_column=Column(JSON))
    incident_type: Optional[str] = None
    summarized_at: Optional[datetime] = None
    # `closed`: thread has gone idle past THREAD_GAP_SEC; auto-summarizer
    # only touches closed threads. `False` means it may still gain events.
    closed: bool = Field(default=False, index=True)
    # `is_noise`: the summarizer judged the cluster unintelligible / pure noise.
    # The dashboard hides these by default (with a "Show noise" toggle).
    is_noise: bool = Field(default=False, index=True)


class WeatherAlertRow(SQLModel, table=True):
    """Active NWS watch/warning/advisory (api.weather.gov) for the Tucson point.
    Deduped by `alert_id`; the monsoon digest reads the currently-active ones."""
    __tablename__ = "weather_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    alert_id: str = Field(index=True)
    event: str = Field(index=True)
    severity: Optional[str] = None
    certainty: Optional[str] = None
    urgency: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    area_desc: Optional[str] = None
    status: Optional[str] = None
    message_type: Optional[str] = None
    onset: Optional[datetime] = None
    expires: Optional[datetime] = Field(default=None, index=True)
    sent: Optional[datetime] = None
    fetched_at: datetime = Field(index=True)


class HourlySummaryRow(SQLModel, table=True):
    """An hourly rollup of *all* events across sources — a wide-angle complement
    to the per-conversation threads. Written by `agents/hourly_summary.py` once
    an hour; the dashboard's "Last hour" tab reads the latest plus a history.
    """
    __tablename__ = "hourly_summaries"

    id: Optional[int] = Field(default=None, primary_key=True)
    generated_at: datetime = Field(index=True)
    window_start: datetime = Field(index=True)
    window_end: datetime = Field(index=True)
    summary: Optional[str] = None
    event_count: int = 0
    # counts per transmission_type, e.g. {"fire": 12, "ems": 8}
    by_type: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # short list of the hour's most notable incidents
    top_incidents: Optional[list] = Field(default=None, sa_column=Column(JSON))
    severity_max: Optional[str] = None
    gauge_note: Optional[str] = None
    weather_note: Optional[str] = None


class AlertRow(SQLModel, table=True):
    """Persisted alert history. Written by `alert_node` (rule-based) and by
    `monsoon_digest` whenever it returns `should_alert=True`."""
    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    source: str = Field(index=True)  # "rule" | "monsoon_digest"
    transcription_id: Optional[int] = Field(default=None, index=True)
    should_alert: bool = True  # always True for persisted rows
    reason: Optional[str] = None
    summary: Optional[str] = None
    correlation_note: Optional[str] = None
    correlated_event_ids: Optional[list] = Field(default=None, sa_column=Column(JSON))


_engine = None


def _db_path() -> Path:
    return Path(os.getenv("DB_PATH", "./data/events.db")).expanduser()


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

    SQLModel.metadata.create_all(_engine)
    _migrate_columns(_engine)
    return _engine


# Columns added to existing tables after their first release. SQLModel's
# `create_all` only creates *missing tables*, never new columns on an existing
# one, so we add them by hand. Idempotent: a column is only added if PRAGMA
# table_info reports it missing. (lat S/N etc. are nullable/defaulted so the
# ALTER is safe on a live DB.)
_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "event_threads": [
        ("source", "VARCHAR DEFAULT 'analog'"),
        ("talkgroup_id", "INTEGER"),
        ("is_noise", "BOOLEAN DEFAULT 0"),
    ],
    "transcription_events": [
        ("corrected_text", "VARCHAR"),
    ],
}


def _migrate_columns(engine) -> None:
    from sqlalchemy import text

    with engine.connect() as conn:
        for table, columns in _COLUMN_MIGRATIONS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                # Table doesn't exist in this DB (PRAGMA returns no rows) — nothing
                # to migrate. create_all() owns table creation; we only add columns.
                continue
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_{name} ON {table} ({name})"
                    ))
        conn.commit()


def get_session() -> Session:
    return Session(get_engine())
