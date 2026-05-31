"""USGS IV parser tests — against a frozen real response (no network)."""

import json
from pathlib import Path

from ingestion.usgs_client import parse_usgs_iv

_FIXTURE = Path(__file__).parent / "fixtures" / "usgs_iv.json"


def _payload():
    return json.loads(_FIXTURE.read_text())


def test_parses_one_reading_per_site():
    readings = parse_usgs_iv(_payload())
    assert readings, "expected gauge readings from the fixture"
    # One merged reading per site (params combined), not one per time series.
    site_ids = [r.site_id for r in readings]
    assert len(site_ids) == len(set(site_ids)), "sites must be merged, not duplicated"
    assert all(r.source == "usgs" for r in readings)


def test_merges_discharge_and_stage_for_a_site():
    readings = {r.site_id: r for r in parse_usgs_iv(_payload())}
    santa_cruz = readings["09482500"]  # Santa Cruz at Tucson reports 00060 + 00065
    assert santa_cruz.discharge_cfs is not None
    assert santa_cruz.gage_height_ft is not None
    assert "SANTA CRUZ" in (santa_cruz.site_name or "").upper()
    assert santa_cruz.lat and santa_cruz.lon


def test_no_data_sentinel_dropped_negative_stage_kept():
    readings = parse_usgs_iv(_payload())
    for r in readings:
        # The -999999 sentinel must never survive as a real value...
        assert r.discharge_cfs != -999999
        assert r.gage_height_ft != -999999
        assert r.precip_in != -999999
    # ...but a legitimately negative gage height is preserved (low-flow stage).
    sabino = {r.site_id: r for r in readings}["09484000"]
    assert sabino.gage_height_ft is not None and sabino.gage_height_ft < 0


def test_timestamp_is_timezone_aware_utc():
    r = parse_usgs_iv(_payload())[0]
    assert r.timestamp.tzinfo is not None
    assert r.timestamp.utcoffset().total_seconds() == 0


def test_empty_payload_yields_nothing():
    assert parse_usgs_iv({}) == []
    assert parse_usgs_iv({"value": {"timeSeries": []}}) == []
