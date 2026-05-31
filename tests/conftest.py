"""Shared pytest fixtures: frozen transcript + APRS sample data.

These back the agent and APRS tests so sample data lives in one place
(`tests/fixtures/*.json`) instead of being scattered as inline literals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.schemas import TranscriptionEvent

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((_FIXTURE_DIR / name).read_text())


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the DB at a throwaway SQLite file and reset the cached engine.

    Tests that seed rows (gauges, transcripts, APRS) and read them back via
    db.queries use this so they never touch the real ./data/events.db.
    """
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    yield db_file
    database_module._engine = None


@pytest.fixture(scope="session")
def transcript_samples() -> list[dict]:
    """20 frozen transcript records (raw dicts, tagged by `category`)."""
    return _load("transcripts.json")


@pytest.fixture(scope="session")
def transcript_events(transcript_samples) -> list[TranscriptionEvent]:
    """The transcript samples as TranscriptionEvent models."""
    now = datetime.now(timezone.utc)
    events = []
    for rec in transcript_samples:
        events.append(
            TranscriptionEvent(
                timestamp=now,
                frequency_mhz=rec["frequency_mhz"],
                raw_text=rec["raw_text"],
                duration_sec=rec["duration_sec"],
                source=rec.get("source", "analog"),
                talkgroup_id=rec.get("talkgroup_id"),
            )
        )
    return events


@pytest.fixture(scope="session")
def transcripts_by_category(transcript_samples):
    """Callable: category name -> list of matching raw transcript dicts."""

    def _get(category: str) -> list[dict]:
        return [r for r in transcript_samples if r["category"] == category]

    return _get


@pytest.fixture(scope="session")
def hallucination_texts(transcript_samples) -> list[str]:
    """Just the raw_text of the known Whisper-hallucination samples."""
    return [r["raw_text"] for r in transcript_samples if r["category"] == "hallucination"]


@pytest.fixture(scope="session")
def aprs_packets() -> list[dict]:
    """10 parsed aprslib-style packet records (tagged by `category`)."""
    return _load("aprs_packets.json")


@pytest.fixture(scope="session")
def aprs_packets_by_category(aprs_packets):
    """Callable: category name -> the matching packet dict (the inner `packet`)."""

    def _get(category: str) -> dict:
        for rec in aprs_packets:
            if rec["category"] == category:
                return rec["packet"]
        raise KeyError(category)

    return _get
