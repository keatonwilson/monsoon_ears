"""Thread clustering tests."""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    yield db_file
    database_module._engine = None


def _insert(ts: datetime, freq: float = 154.37, text: str = "x") -> int:
    from db.database import TranscriptionEventRow, get_session
    with get_session() as s:
        row = TranscriptionEventRow(
            timestamp=ts, frequency_mhz=freq, raw_text=text, duration_sec=2.0,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def test_close_events_within_gap_become_one_thread(temp_db):
    from db.queries import recent_threads, stitch_events_into_threads

    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    _insert(base)
    _insert(base + timedelta(seconds=30))
    _insert(base + timedelta(seconds=60))
    stitch_events_into_threads()

    threads = recent_threads()
    assert len(threads) == 1
    assert threads[0].event_count == 3


def test_gap_longer_than_threshold_splits_threads(temp_db):
    from db.queries import recent_threads, stitch_events_into_threads

    base = datetime.now(timezone.utc) - timedelta(minutes=10)
    _insert(base)
    _insert(base + timedelta(seconds=200))  # > 90s
    stitch_events_into_threads()

    threads = recent_threads()
    assert len(threads) == 2


def test_different_frequencies_split_threads(temp_db):
    from db.queries import recent_threads, stitch_events_into_threads

    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    _insert(base, freq=154.37)
    _insert(base + timedelta(seconds=10), freq=153.815)
    stitch_events_into_threads()

    threads = recent_threads()
    assert len(threads) == 2


def test_insert_transcription_assigns_thread_inline(temp_db):
    from db.queries import insert_transcription, recent_threads
    from models.schemas import TranscriptionEvent

    base = datetime.now(timezone.utc) - timedelta(minutes=2)
    insert_transcription(TranscriptionEvent(
        timestamp=base, frequency_mhz=154.37, raw_text="a", duration_sec=2.0,
    ))
    insert_transcription(TranscriptionEvent(
        timestamp=base + timedelta(seconds=20), frequency_mhz=154.37, raw_text="b",
        duration_sec=2.0,
    ))
    threads = recent_threads()
    assert len(threads) == 1
    assert threads[0].event_count == 2


def test_close_idle_threads_marks_old_ones(temp_db):
    from db.queries import (
        close_idle_threads,
        recent_threads,
        stitch_events_into_threads,
    )

    base = datetime.now(timezone.utc) - timedelta(minutes=10)
    _insert(base)
    stitch_events_into_threads()
    # Pretend we're checking 5 minutes after the event — well past gap.
    just_closed = close_idle_threads(now=base + timedelta(minutes=5))
    assert len(just_closed) == 1
    threads = recent_threads()
    assert threads[0].closed is True


def test_threads_needing_summary_only_returns_closed_unsummarized(temp_db):
    from db.queries import (
        close_idle_threads,
        threads_needing_summary,
        stitch_events_into_threads,
        update_thread_summary,
    )

    base = datetime.now(timezone.utc) - timedelta(minutes=20)
    _insert(base)
    _insert(base + timedelta(minutes=10))  # second thread
    stitch_events_into_threads()
    close_idle_threads(now=base + timedelta(minutes=30))

    pending = threads_needing_summary()
    assert len(pending) == 2

    update_thread_summary(
        pending[0].id,
        summary="x", transmission_type="ems", severity="low",
        locations=None, units=None, incident_type=None,
    )
    pending2 = threads_needing_summary()
    assert len(pending2) == 1
