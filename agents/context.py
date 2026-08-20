"""Situational snapshot — a compact read of "how monsoon-y is it right now?"

The SDR supervisor can only point the single dongle at one RF leg at a time
(analog scan vs. op25/P25). The Band Manager (agents/band_manager.py) decides how
to split that time, and to do so it needs a small, cheap summary of current
conditions drawn from data we *already* have in the DB — no new sources, no
network. This module produces that summary.

The same three signals the monsoon digest correlates over feed this snapshot:
recent flood/fire/EMS voice traffic, official stream/rain gauges, and APRS
backyard weather (see agents/alert.py:monsoon_digest). We reduce them to a few
scalars plus a one-line text rendering the agent can read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.locale import UTC_OFFSET_HOURS, in_season
from db.queries import recent_aprs, recent_flood_events, recent_gauges

_LOCAL_UTC_OFFSET = timedelta(hours=UTC_OFFSET_HOURS)


@dataclass(frozen=True)
class Situation:
    """Compact, serialisable read of current monsoon-relevant activity."""

    flood_event_count: int          # fire/EMS/flood-control transmissions in window
    gauge_reading_count: int        # gauge readings seen in window
    max_discharge_cfs: float | None # highest stream discharge across all gauges
    max_gage_height_ft: float | None
    aprs_packet_count: int
    aprs_rain_max_in: float | None  # heaviest recent rainfall reported via APRS
    hour_local: int                 # 0-23, local time (config.locale.UTC_OFFSET_HOURS)
    monsoon_season: bool            # inside the configured hazard-season window

    def summary_line(self) -> str:
        """One-line human/agent-readable rendering."""
        season = "in-season" if self.monsoon_season else "off-season"
        disch = f"{self.max_discharge_cfs:.0f}cfs" if self.max_discharge_cfs is not None else "n/a"
        rain = f"{self.aprs_rain_max_in:.2f}in" if self.aprs_rain_max_in is not None else "n/a"
        return (
            f"{self.hour_local:02d}:00 local, {season}; "
            f"flood/fire/EMS traffic={self.flood_event_count}, "
            f"max gauge discharge={disch}, "
            f"APRS rain(max)={rain} ({self.aprs_packet_count} pkts), "
            f"gauge readings={self.gauge_reading_count}"
        )


def _safe_max(values) -> float | None:
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def situational_snapshot(
    voice_window_min: int = 60,
    gauge_window_min: int = 60,
    aprs_window_min: int = 30,
    now: datetime | None = None,
) -> Situation:
    """Build a Situation from the same DB signals the monsoon digest uses.

    Pulls via the shared db.queries helpers, so tests seed it the same way they
    seed the digest (a temp DB_PATH + inserted rows). No network, no LLM.
    """
    now = now or datetime.now(timezone.utc)
    local = now + _LOCAL_UTC_OFFSET

    voice_rows = recent_flood_events(minutes=voice_window_min)
    gauge_rows = recent_gauges(minutes=gauge_window_min)
    aprs_rows = recent_aprs(minutes=aprs_window_min)

    return Situation(
        flood_event_count=len(voice_rows),
        gauge_reading_count=len(gauge_rows),
        max_discharge_cfs=_safe_max(r.discharge_cfs for r in gauge_rows),
        max_gage_height_ft=_safe_max(r.gage_height_ft for r in gauge_rows),
        aprs_packet_count=len(aprs_rows),
        aprs_rain_max_in=_safe_max(r.rainfall_in for r in aprs_rows),
        hour_local=local.hour,
        monsoon_season=in_season(local.month, local.day),
    )
