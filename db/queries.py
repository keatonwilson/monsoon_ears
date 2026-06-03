from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from db.database import (
    AlertRow,
    APRSEventRow,
    EventThreadRow,
    GaugeReadingRow,
    TranscriptionEventRow,
    WeatherAlertRow,
    get_session,
)
from models.schemas import (
    AlertDecision,
    APRSEvent,
    ClassifiedEvent,
    ExtractedEvent,
    GaugeReading,
    TranscriptionEvent,
    TransmissionType,
    WeatherAlert,
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
        row.corrected_text = e.corrected_text
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


def insert_gauge_reading(reading: GaugeReading) -> int:
    row = GaugeReadingRow(
        timestamp=reading.timestamp,
        source=reading.source,
        site_id=reading.site_id,
        site_name=reading.site_name,
        lat=reading.lat,
        lon=reading.lon,
        discharge_cfs=reading.discharge_cfs,
        gage_height_ft=reading.gage_height_ft,
        precip_in=reading.precip_in,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def insert_weather_alert(alert: WeatherAlert) -> Optional[int]:
    """Persist an NWS alert, deduped by alert_id. Returns the new row id, or
    None if we already have this alert_id (NWS re-serves active alerts on every
    poll)."""
    with get_session() as session:
        existing = session.exec(
            select(WeatherAlertRow.id).where(WeatherAlertRow.alert_id == alert.alert_id).limit(1)
        ).first()
        if existing is not None:
            return None
        row = WeatherAlertRow(
            alert_id=alert.alert_id,
            event=alert.event,
            severity=alert.severity,
            certainty=alert.certainty,
            urgency=alert.urgency,
            headline=alert.headline,
            description=alert.description,
            area_desc=alert.area_desc,
            status=alert.status,
            message_type=alert.message_type,
            onset=alert.onset,
            expires=alert.expires,
            sent=alert.sent,
            fetched_at=alert.fetched_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def active_weather_alerts(now: Optional[datetime] = None) -> list[WeatherAlertRow]:
    """NWS alerts that haven't expired yet (null expiry = treated as active).
    Newest first. Drives the digest's weather-alert section and /weather."""
    now = now or datetime.now(timezone.utc)
    with get_session() as session:
        stmt = (
            select(WeatherAlertRow)
            .where(
                (WeatherAlertRow.expires.is_(None)) | (WeatherAlertRow.expires >= now)
            )
            .order_by(WeatherAlertRow.fetched_at.desc())
        )
        return list(session.exec(stmt))


def recent_gauges(minutes: int = 60) -> list[GaugeReadingRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_session() as session:
        stmt = (
            select(GaugeReadingRow)
            .where(GaugeReadingRow.timestamp >= cutoff)
            .order_by(GaugeReadingRow.id.desc())
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
    alerting_only: bool = True,
) -> list[AlertRow]:
    """Recent alert history. `alerting_only` (default) keeps this a true alert
    log: the monsoon digest now persists every verdict (incl. should_alert=False
    so /summary reflects the latest run), and those non-alert rows must not show
    up here."""
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
        if alerting_only:
            stmt = stmt.where(AlertRow.should_alert == True)  # noqa: E712
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

    Lookup: a same-channel thread whose `end_timestamp` is within THREAD_GAP_SEC
    of `event.timestamp`. "Same channel" means the same talkgroup for P25 (every
    P25 event shares frequency_mhz=0.0, so frequency alone would merge all
    talkgroups into one thread) and the same frequency for analog. The newest
    match wins.
    """
    cutoff = event.timestamp - timedelta(seconds=THREAD_GAP_SEC)
    stmt = select(EventThreadRow).where(EventThreadRow.end_timestamp >= cutoff)
    if event.source == "p25":
        stmt = stmt.where(EventThreadRow.source == "p25").where(
            EventThreadRow.talkgroup_id == event.talkgroup_id
        )
    else:
        stmt = stmt.where(EventThreadRow.source == event.source).where(
            EventThreadRow.frequency_mhz == event.frequency_mhz
        )
    stmt = stmt.order_by(EventThreadRow.end_timestamp.desc()).limit(1)
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
        source=event.source,
        talkgroup_id=event.talkgroup_id,
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
    is_noise: bool = False,
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
        row.is_noise = is_noise
        row.summarized_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
