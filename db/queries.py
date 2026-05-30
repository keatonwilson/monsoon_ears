from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from db.database import AlertRow, APRSEventRow, EventThreadRow, TranscriptionEventRow, get_session
from models.schemas import (
    AlertDecision,
    APRSEvent,
    ClassifiedEvent,
    ExtractedEvent,
    TranscriptionEvent,
    TransmissionType,
)


def insert_transcription(event: TranscriptionEvent) -> int:
    row = TranscriptionEventRow(
        timestamp=event.timestamp,
        frequency_mhz=event.frequency_mhz,
        raw_text=event.raw_text,
        duration_sec=event.duration_sec,
        source=event.source,
        talkgroup_id=event.talkgroup_id,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        # Assign the new event to its thread (creating a fresh one if needed).
        # Failures here must not break the capture path — log and move on.
        try:
            _assign_thread_for_event(session, row)
            session.commit()
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "thread assignment failed for event %s; continuing", row.id,
            )
            session.rollback()
        return row.id


def insert_aprs(event: APRSEvent) -> int:
    row = APRSEventRow(
        timestamp=event.timestamp,
        callsign=event.callsign,
        lat=event.lat,
        lon=event.lon,
        symbol=event.symbol,
        comment=event.comment,
        temp_f=event.temp_f,
        rainfall_in=event.rainfall_in,
        wind_mph=event.wind_mph,
        source=event.source,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def recent_transcriptions(limit: int = 20, source: Optional[str] = None) -> list[TranscriptionEventRow]:
    with get_session() as session:
        stmt = select(TranscriptionEventRow).order_by(TranscriptionEventRow.id.desc()).limit(limit)
        if source:
            stmt = stmt.where(TranscriptionEventRow.source == source)
        return list(session.exec(stmt))


def update_classification(row_id: int, c: ClassifiedEvent) -> None:
    with get_session() as session:
        row = session.get(TranscriptionEventRow, row_id)
        if row is None:
            raise ValueError(f"transcription_events row {row_id} not found")
        row.transmission_type = c.transmission_type.value
        row.confidence = c.confidence
        row.language = c.language
        session.add(row)
        session.commit()


def update_extraction(row_id: int, e: ExtractedEvent) -> None:
    with get_session() as session:
        row = session.get(TranscriptionEventRow, row_id)
        if row is None:
            raise ValueError(f"transcription_events row {row_id} not found")
        row.locations = e.locations
        row.incident_type = e.incident_type
        row.callsigns = e.callsigns
        row.units = e.units
        row.status_codes = e.status_codes
        row.severity = e.severity.value
        row.lat = e.lat
        row.lon = e.lon
        row.wash_name = e.wash_name
        row.road_closure = e.road_closure
        session.add(row)
        session.commit()


def fetch_unclassified(limit: int = 10) -> list[TranscriptionEventRow]:
    with get_session() as session:
        stmt = (
            select(TranscriptionEventRow)
            .where(TranscriptionEventRow.transmission_type.is_(None))
            .order_by(TranscriptionEventRow.id.asc())
            .limit(limit)
        )
        return list(session.exec(stmt))


# Transmission types treated as "relevant for the monsoon digest." Fire and EMS
# matter because flooding triggers rescues; flood_control is the direct match.
_DIGEST_TYPES = (
    TransmissionType.FIRE.value,
    TransmissionType.EMS.value,
    TransmissionType.FLOOD_CONTROL.value,
)


def recent_flood_events(minutes: int = 60) -> list[TranscriptionEventRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_session() as session:
        stmt = (
            select(TranscriptionEventRow)
            .where(TranscriptionEventRow.timestamp >= cutoff)
            .where(TranscriptionEventRow.transmission_type.in_(_DIGEST_TYPES))
            .order_by(TranscriptionEventRow.id.desc())
        )
        return list(session.exec(stmt))


def recent_aprs(minutes: int = 30) -> list[APRSEventRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_session() as session:
        stmt = (
            select(APRSEventRow)
            .where(APRSEventRow.timestamp >= cutoff)
            .order_by(APRSEventRow.id.desc())
        )
        return list(session.exec(stmt))


# --- Phase 04: alert persistence + dashboard reads -----------------------------


def insert_alert(
    source: str,
    decision: AlertDecision,
    transcription_id: Optional[int] = None,
) -> int:
    """Persist an alert decision. Returns the new row id."""
    row = AlertRow(
        timestamp=datetime.now(timezone.utc),
        source=source,
        transcription_id=transcription_id,
        should_alert=decision.should_alert,
        reason=decision.reason,
        summary=decision.summary,
        correlation_note=decision.correlation_note,
        correlated_event_ids=decision.correlated_event_ids or None,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def recent_alerts(
    limit: int = 50,
    since_minutes: int = 24 * 60,
    source: Optional[str] = None,
) -> list[AlertRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    with get_session() as session:
        stmt = (
            select(AlertRow)
            .where(AlertRow.timestamp >= cutoff)
            .order_by(AlertRow.id.desc())
            .limit(limit)
        )
        if source:
            stmt = stmt.where(AlertRow.source == source)
        return list(session.exec(stmt))


def latest_digest_alert() -> Optional[AlertRow]:
    """Most recent monsoon_digest-sourced alert, regardless of age."""
    with get_session() as session:
        stmt = (
            select(AlertRow)
            .where(AlertRow.source == "monsoon_digest")
            .order_by(AlertRow.id.desc())
            .limit(1)
        )
        result = list(session.exec(stmt))
        return result[0] if result else None


def events_since(
    since_minutes: int,
    limit: int = 500,
    source: Optional[str] = None,
    transmission_type: Optional[str] = None,
) -> list[TranscriptionEventRow]:
    """Generic time-windowed event query — drives /events with filters."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    with get_session() as session:
        stmt = (
            select(TranscriptionEventRow)
            .where(TranscriptionEventRow.timestamp >= cutoff)
            .order_by(TranscriptionEventRow.id.desc())
            .limit(limit)
        )
        if source:
            stmt = stmt.where(TranscriptionEventRow.source == source)
        if transmission_type:
            stmt = stmt.where(TranscriptionEventRow.transmission_type == transmission_type)
        return list(session.exec(stmt))


def event_by_id(row_id: int) -> Optional[TranscriptionEventRow]:
    with get_session() as session:
        return session.get(TranscriptionEventRow, row_id)


# --- Event-thread clustering ---------------------------------------------------

THREAD_GAP_SEC = 90  # max inter-event gap on a freq to be considered the same thread


def _assign_thread_for_event(session, event: TranscriptionEventRow) -> EventThreadRow:
    """Find or create the thread this event belongs to.

    Lookup: any thread on the same frequency whose `end_timestamp` is within
    THREAD_GAP_SEC of `event.timestamp`. The newest match wins.
    """
    cutoff = event.timestamp - timedelta(seconds=THREAD_GAP_SEC)
    stmt = (
        select(EventThreadRow)
        .where(EventThreadRow.frequency_mhz == event.frequency_mhz)
        .where(EventThreadRow.end_timestamp >= cutoff)
        .order_by(EventThreadRow.end_timestamp.desc())
        .limit(1)
    )
    existing = session.exec(stmt).first()
    if existing is not None:
        ids = list(existing.event_ids or [])
        if event.id not in ids:
            ids.append(event.id)
        existing.event_ids = ids
        existing.event_count = len(ids)
        existing.end_timestamp = max(existing.end_timestamp, event.timestamp)
        existing.summarized_at = None  # stale; re-summarize on close
        session.add(existing)
        return existing

    fresh = EventThreadRow(
        frequency_mhz=event.frequency_mhz,
        start_timestamp=event.timestamp,
        end_timestamp=event.timestamp,
        event_count=1,
        event_ids=[event.id],
        closed=False,
    )
    session.add(fresh)
    session.flush()  # populate id
    return fresh


def stitch_events_into_threads(event_ids: Optional[list[int]] = None) -> int:
    """Bulk-stitch existing events into threads. Used for backfill.

    If `event_ids` is None, stitches every row in the table that doesn't yet
    appear in any thread's `event_ids`. Returns count of threads touched.
    """
    with get_session() as session:
        if event_ids is None:
            existing = session.exec(select(EventThreadRow.event_ids)).all()
            already_in_thread = set()
            for ids in existing:
                if ids:
                    already_in_thread.update(ids)
            stmt = (
                select(TranscriptionEventRow)
                .order_by(TranscriptionEventRow.timestamp.asc())
            )
            rows = [
                r for r in session.exec(stmt)
                if r.id not in already_in_thread
            ]
        else:
            rows = []
            for rid in event_ids:
                row = session.get(TranscriptionEventRow, rid)
                if row is not None:
                    rows.append(row)
            rows.sort(key=lambda r: r.timestamp)

        touched = set()
        for r in rows:
            t = _assign_thread_for_event(session, r)
            touched.add(t.id)
        session.commit()
        return len(touched)


def close_idle_threads(now: Optional[datetime] = None) -> list[int]:
    """Mark any open thread whose newest event is older than THREAD_GAP_SEC
    as closed. Returns the ids of threads that were just closed (still need
    a summary).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=THREAD_GAP_SEC)
    just_closed: list[int] = []
    with get_session() as session:
        stmt = (
            select(EventThreadRow)
            .where(EventThreadRow.closed == False)  # noqa: E712
            .where(EventThreadRow.end_timestamp < cutoff)
        )
        for thread in session.exec(stmt):
            thread.closed = True
            session.add(thread)
            just_closed.append(thread.id)
        session.commit()
    return just_closed


def thread_by_id(thread_id: int) -> Optional[EventThreadRow]:
    with get_session() as session:
        return session.get(EventThreadRow, thread_id)


def events_for_thread(thread_id: int) -> list[TranscriptionEventRow]:
    """Return the constituent events of a thread, oldest first."""
    with get_session() as session:
        thread = session.get(EventThreadRow, thread_id)
        if thread is None or not thread.event_ids:
            return []
        ids = thread.event_ids
        rows = [r for r in (session.get(TranscriptionEventRow, i) for i in ids) if r is not None]
        rows.sort(key=lambda r: r.timestamp)
        return rows


def recent_threads(limit: int = 50, since_minutes: int = 24 * 60) -> list[EventThreadRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    with get_session() as session:
        stmt = (
            select(EventThreadRow)
            .where(EventThreadRow.start_timestamp >= cutoff)
            .order_by(EventThreadRow.end_timestamp.desc())
            .limit(limit)
        )
        return list(session.exec(stmt))


def threads_needing_summary(limit: int = 25) -> list[EventThreadRow]:
    """Closed threads that haven't been summarized yet."""
    with get_session() as session:
        stmt = (
            select(EventThreadRow)
            .where(EventThreadRow.closed == True)  # noqa: E712
            .where(EventThreadRow.summarized_at.is_(None))
            .order_by(EventThreadRow.id.asc())
            .limit(limit)
        )
        return list(session.exec(stmt))


def update_thread_summary(
    thread_id: int,
    *,
    summary: str,
    transmission_type: Optional[str],
    severity: Optional[str],
    locations: Optional[list],
    units: Optional[list],
    incident_type: Optional[str],
) -> None:
    with get_session() as session:
        row = session.get(EventThreadRow, thread_id)
        if row is None:
            raise ValueError(f"event_threads row {thread_id} not found")
        row.summary = summary
        row.transmission_type = transmission_type
        row.severity = severity
        row.locations = locations
        row.units = units
        row.incident_type = incident_type
        row.summarized_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
