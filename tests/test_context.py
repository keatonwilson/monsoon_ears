"""agents/context.py — situational_snapshot reduces DB signals correctly."""

from datetime import datetime, timedelta, timezone

from agents.context import Situation, situational_snapshot


def _seed_gauge(**kw):
    from db.queries import insert_gauge_reading
    from models.schemas import GaugeReading

    base = dict(
        timestamp=datetime.now(timezone.utc),
        source="usgs",
        site_id="09485700",
        site_name="Rillito Creek at Dodge Blvd",
    )
    base.update(kw)
    insert_gauge_reading(GaugeReading(**base))


def test_empty_db_is_quiet(temp_db):
    snap = situational_snapshot()
    assert snap.flood_event_count == 0
    assert snap.gauge_reading_count == 0
    assert snap.max_discharge_cfs is None
    assert snap.aprs_rain_max_in is None
    # summary_line never crashes on all-None
    assert "max gauge discharge=n/a" in snap.summary_line()


def test_snapshot_takes_max_discharge_across_gauges(temp_db):
    _seed_gauge(discharge_cfs=120.0, gage_height_ft=3.1)
    _seed_gauge(site_id="09484000", site_name="Sabino", discharge_cfs=910.0, gage_height_ft=7.8)
    snap = situational_snapshot()
    assert snap.gauge_reading_count == 2
    assert snap.max_discharge_cfs == 910.0
    assert snap.max_gage_height_ft == 7.8


def test_snapshot_counts_flood_traffic_and_aprs_rain(temp_db):
    from db.database import APRSEventRow, TranscriptionEventRow, get_session

    now = datetime.now(timezone.utc)
    with get_session() as s:
        s.add(TranscriptionEventRow(
            timestamp=now - timedelta(minutes=3), frequency_mhz=154.37,
            raw_text="swift water rescue at the wash", duration_sec=3.0,
            transmission_type="flood_control",
        ))
        s.add(APRSEventRow(
            timestamp=now - timedelta(minutes=2), callsign="W7ABC",
            rainfall_in=0.75, temp_f=78.0,
        ))
        s.add(APRSEventRow(
            timestamp=now - timedelta(minutes=1), callsign="W7XYZ",
            rainfall_in=1.4, temp_f=76.0,
        ))
        s.commit()

    snap = situational_snapshot()
    assert snap.flood_event_count == 1
    assert snap.aprs_packet_count == 2
    assert snap.aprs_rain_max_in == 1.4


def test_monsoon_season_flag_and_local_hour(temp_db):
    # Fixed UTC instant: 2026-07-15 03:00 UTC -> 2026-07-14 20:00 Tucson (UTC-7),
    # squarely inside the June 15 – Sept 30 monsoon window.
    in_season = situational_snapshot(now=datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc))
    assert in_season.monsoon_season is True
    assert in_season.hour_local == 20

    # January is off-season.
    off = situational_snapshot(now=datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc))
    assert off.monsoon_season is False
