"""summarize_thread + summarize_pending tests, mocked Anthropic."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.summarize import ThreadSummary, summarize_pending, summarize_thread
from models.schemas import Severity, TransmissionType


class FakeMessages:
    def __init__(self, response: ThreadSummary):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: ThreadSummary):
        self.messages = FakeMessages(response)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import db.database as database_module
    database_module._engine = None
    yield db_file
    database_module._engine = None


def _seed_thread(n_events: int = 3):
    """Insert N events 30s apart at 154.37; stitch into one thread."""
    from db.queries import insert_transcription, stitch_events_into_threads
    from models.schemas import TranscriptionEvent
    base = datetime.now(timezone.utc) - timedelta(minutes=10)
    ids = []
    for i in range(n_events):
        ids.append(insert_transcription(TranscriptionEvent(
            timestamp=base + timedelta(seconds=30 * i),
            frequency_mhz=154.37,
            raw_text=f"fragment {i}",
            duration_sec=2.0,
        )))
    # Threads should auto-form via insert_transcription, but stitch as belt+suspenders.
    stitch_events_into_threads()
    return ids


def test_summarize_thread_persists_summary(temp_db):
    _seed_thread()
    from db.queries import recent_threads, thread_by_id

    thread = recent_threads()[0]
    response = ThreadSummary(
        summary="Engine 31 dispatched to a structure fire at Main and Oracle.",
        transmission_type=TransmissionType.FIRE,
        severity=Severity.HIGH,
        locations=["Main and Oracle"],
        units=["Engine 31"],
        incident_type="structure fire",
    )
    summarize_thread(thread.id, client=FakeClient(response))

    updated = thread_by_id(thread.id)
    assert updated.summary and "Engine 31" in updated.summary
    assert updated.transmission_type == "fire"
    assert updated.severity == "high"
    assert updated.units == ["Engine 31"]
    assert updated.summarized_at is not None


def test_summarize_pending_only_processes_closed_unsummarized(temp_db):
    """summarize_pending should ignore open threads entirely."""
    from db.queries import close_idle_threads, recent_threads

    _seed_thread(n_events=2)
    # Threads are open by default; summarize_pending should be a no-op.
    response = ThreadSummary(
        summary="x", transmission_type=TransmissionType.UNKNOWN,
        severity=Severity.UNKNOWN, locations=[], units=[],
    )
    n = summarize_pending(client=FakeClient(response))
    assert n == 0
    # Now close the threads (pretend enough time passed).
    close_idle_threads(now=datetime.now(timezone.utc) + timedelta(hours=1))
    n2 = summarize_pending(client=FakeClient(response))
    assert n2 == 1
    # Re-running should be a no-op now that the thread is summarized.
    n3 = summarize_pending(client=FakeClient(response))
    assert n3 == 0


def test_summarize_thread_uses_configurable_model(temp_db):
    _seed_thread(n_events=2)
    from db.queries import recent_threads

    thread = recent_threads()[0]
    client = FakeClient(ThreadSummary(
        summary="x", transmission_type=TransmissionType.UNKNOWN,
        severity=Severity.UNKNOWN, locations=[], units=[],
    ))
    summarize_thread(thread.id, client=client, model="claude-haiku-4-5-20251001")
    assert client.messages.calls[0]["model"] == "claude-haiku-4-5-20251001"
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "fragment 0" in prompt and "fragment 1" in prompt
    assert "154.37" in prompt
