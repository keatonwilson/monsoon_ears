from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from db.database import APRSEventRow, TranscriptionEventRow, get_session
from models.schemas import (
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
