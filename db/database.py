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
    return _engine


def get_session() -> Session:
    return Session(get_engine())
