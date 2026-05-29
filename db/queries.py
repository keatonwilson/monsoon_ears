from typing import Optional

from sqlmodel import select

from db.database import APRSEventRow, TranscriptionEventRow, get_session
from models.schemas import APRSEvent, TranscriptionEvent


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
