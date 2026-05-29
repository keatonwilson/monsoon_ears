from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class TransmissionType(str, Enum):
    FIRE = "fire"
    EMS = "ems"
    POLICE = "police"
    HAM = "ham"
    WEATHER = "weather"
    APRS = "aprs"
    FLOOD_CONTROL = "flood_control"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class TranscriptionEvent(BaseModel):
    id: Optional[int] = None
    timestamp: datetime
    frequency_mhz: float
    raw_text: str
    duration_sec: float
    source: str = "analog"  # "analog" | "p25"
    talkgroup_id: Optional[int] = None


class ClassifiedEvent(TranscriptionEvent):
    transmission_type: TransmissionType
    confidence: float
    language: str = "en"


class ExtractedEvent(ClassifiedEvent):
    locations: list[str] = []
    incident_type: Optional[str] = None
    callsigns: list[str] = []
    units: list[str] = []
    status_codes: list[str] = []
    severity: Severity = Severity.UNKNOWN
    lat: Optional[float] = None
    lon: Optional[float] = None
    wash_name: Optional[str] = None
    road_closure: Optional[bool] = None


class APRSEvent(BaseModel):
    id: Optional[int] = None
    timestamp: datetime
    callsign: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    symbol: Optional[str] = None
    comment: Optional[str] = None
    temp_f: Optional[float] = None
    rainfall_in: Optional[float] = None
    wind_mph: Optional[float] = None
    source: str = "aprs"


class AlertDecision(BaseModel):
    should_alert: bool
    reason: Optional[str] = None
    summary: Optional[str] = None
    correlated_event_ids: list[int] = []
    correlation_note: Optional[str] = None
