"""packet_to_event mapping — pure transform, no network.

Sample packets come from tests/fixtures/aprs_packets.json. One test additionally
pins aprslib's real parsing behavior (it normalizes wire °F to °C); that test is
skipped where aprslib isn't installed (it's a `pi` extra, absent on dev Macs).
"""

import pytest

from ingestion.aprs_is_client import aprs_login_params, packet_to_event


def test_standard_weather_converts_to_imperial(aprs_packets_by_category):
    # aprslib hands us metric: 22.22 °C, 2.54 mm rain, 6.7 m/s wind.
    event = packet_to_event(aprs_packets_by_category("standard_wx"))
    assert event is not None
    assert event.callsign == "N7XYZ-13"
    assert event.symbol == "_"
    # 22.22 °C → 72 °F, 2.54 mm → 0.10 in, 6.7 m/s → ~14.99 mph
    assert event.temp_f is not None and abs(event.temp_f - 72.0) < 0.1
    assert event.rainfall_in is not None and abs(event.rainfall_in - 0.10) < 0.001
    assert event.wind_mph is not None and abs(event.wind_mph - 14.99) < 0.05


def test_hot_summer_temp_in_range(aprs_packets_by_category):
    event = packet_to_event(aprs_packets_by_category("hot_summer"))
    assert event is not None and abs(event.temp_f - 109.0) < 0.1


def test_negative_temp_in_range(aprs_packets_by_category):
    event = packet_to_event(aprs_packets_by_category("negative_temp"))
    assert event is not None and abs(event.temp_f - (-5.0)) < 0.1


def test_garbage_temp_is_clamped_to_none(aprs_packets_by_category):
    """A mis-decoded 200 °C (~392 °F) reading must be dropped, not stored."""
    event = packet_to_event(aprs_packets_by_category("garbage_temp_high"))
    assert event is not None
    assert event.temp_f is None


def test_position_only_has_no_weather(aprs_packets_by_category):
    event = packet_to_event(aprs_packets_by_category("position_only"))
    assert event is not None
    assert event.callsign == "W7ABC-9"
    assert event.temp_f is None


def test_drops_no_callsign(aprs_packets_by_category):
    assert packet_to_event(aprs_packets_by_category("no_callsign")) is None


def test_truncates_long_comment(aprs_packets_by_category):
    event = packet_to_event(aprs_packets_by_category("long_comment"))
    assert event is not None
    assert len(event.comment) == 512


def test_all_fixture_packets_round_trip(aprs_packets):
    """Every fixture is either dropped (no callsign) or produces a sane event."""
    for rec in aprs_packets:
        event = packet_to_event(rec["packet"])
        if rec["category"] == "no_callsign":
            assert event is None
            continue
        assert event is not None
        if event.temp_f is not None:
            assert -40.0 <= event.temp_f <= 140.0
        if event.rainfall_in is not None:
            assert event.rainfall_in >= 0.0
        if event.wind_mph is not None:
            assert event.wind_mph >= 0.0


# --- Login params -----------------------------------------------------------


def test_login_params_default_anonymous(monkeypatch):
    for k in ("APRS_IS_CALLSIGN", "APRS_IS_PASSCODE", "APRS_IS_SERVER", "APRS_IS_FILTER"):
        monkeypatch.delenv(k, raising=False)
    callsign, passcode, server, _filter = aprs_login_params()
    assert callsign == "N0CALL"
    assert passcode == "-1"  # receive-only


def test_login_params_real_callsign_stays_receive_only(monkeypatch):
    monkeypatch.setenv("APRS_IS_CALLSIGN", "KD7ABC")
    monkeypatch.delenv("APRS_IS_PASSCODE", raising=False)
    callsign, passcode, _server, _filter = aprs_login_params()
    assert callsign == "KD7ABC"
    assert passcode == "-1"  # identified, but no injection rights by default


def test_login_params_blank_env_falls_back(monkeypatch):
    monkeypatch.setenv("APRS_IS_CALLSIGN", "  ")
    monkeypatch.setenv("APRS_IS_PASSCODE", "")
    callsign, passcode, _server, _filter = aprs_login_params()
    assert callsign == "N0CALL"
    assert passcode == "-1"


# --- Empirical: pin aprslib's actual unit handling --------------------------

aprslib = pytest.importorskip("aprslib", reason="aprslib is a `pi` extra")


@pytest.mark.parametrize(
    "raw, expected_c",
    [
        # Wire t072 = 72 °F → aprslib should report 22.22 °C.
        ("N7XYZ-13>APRS,TCPIP*:@092345z3212.60N/11057.00W_180/010g015t072r010", 22.22),
        # Wire t077 = 77 °F (CWOP positionless) → 25.0 °C.
        ("CW1234>APRS,TCPIP*:_10090556c220s004g005t077r000p000P000h50b09900", 25.0),
    ],
)
def test_aprslib_normalizes_fahrenheit_to_celsius(raw, expected_c):
    parsed = aprslib.parse(raw)
    weather = parsed.get("weather") or {}
    assert weather.get("temperature") == pytest.approx(expected_c, abs=0.1)
