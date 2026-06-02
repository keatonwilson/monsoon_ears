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


class GaugeReading(BaseModel):
    """A single reading from a stream/rain gauge (USGS or Pima County ALERT).

    Stream discharge is the strongest flash-flood signal; gage height and
    precip round it out. All measures optional — a given site may report only
    some parameters.
    """
    id: Optional[int] = None
    timestamp: datetime
    source: str  # "usgs" | "pima_alert"
    site_id: str
    site_name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    discharge_cfs: Optional[float] = None
    gage_height_ft: Optional[float] = None
    precip_in: Optional[float] = None


class WeatherAlert(BaseModel):
    """An active NWS watch/warning/advisory from api.weather.gov for the Tucson
    point. A Flash Flood Warning here is the strongest official flood signal —
    it anchors the monsoon digest alongside radio + gauges."""
    id: Optional[int] = None
    alert_id: str                       # NWS properties.id (stable per message)
    event: str                          # e.g. "Flash Flood Warning"
    severity: Optional[str] = None      # Extreme | Severe | Moderate | Minor | Unknown
    certainty: Optional[str] = None
    urgency: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    area_desc: Optional[str] = None
    status: Optional[str] = None        # Actual | Test | ...
    message_type: Optional[str] = None  # Alert | Update | Cancel
    onset: Optional[datetime] = None
    expires: Optional[datetime] = None
    sent: Optional[datetime] = None
    fetched_at: datetime


class AlertDecision(BaseModel):
    should_alert: bool
    reason: Optional[str] = None
    summary: Optional[str] = None
    correlated_event_ids: list[int] = []
    correlation_note: Optional[str] = None
