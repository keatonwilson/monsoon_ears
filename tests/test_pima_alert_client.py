"""Pima ALERT scraper tests — frozen HTML fixture + graceful-failure path."""

from pathlib import Path
from unittest.mock import patch

from ingestion.pima_alert_client import fetch_pima_alert, parse_pima_alert_precip

_FIXTURE = Path(__file__).parent / "fixtures" / "pima_alert_precip.html"


def test_parses_rain_gauges_from_table():
    html = _FIXTURE.read_text(encoding="utf-8", errors="replace")
    readings = parse_pima_alert_precip(html)
    assert len(readings) > 50, "expected many rain gauges in the county table"
    assert all(r.source == "pima_alert" for r in readings)
    # Each is a numeric sensor id with a 1-hour precip value.
    assert all(r.site_id.isdigit() for r in readings)
    assert all(r.precip_in is not None for r in readings)
    # Stream-only fields stay empty (this is the rain table).
    assert all(r.discharge_cfs is None for r in readings)


def test_header_and_area_rows_are_skipped():
    html = _FIXTURE.read_text(encoding="utf-8", errors="replace")
    readings = parse_pima_alert_precip(html)
    names = [r.site_name for r in readings]
    assert "Station Name" not in names  # the header row must not become a reading


def test_garbage_html_yields_nothing():
    assert parse_pima_alert_precip("<html><body>nope</body></html>") == []


def test_fetch_degrades_gracefully_on_error():
    """A network failure must return [] (best-effort), never raise."""
    with patch("requests.get", side_effect=Exception("boom")):
        assert fetch_pima_alert() == []
