"""packet_to_event mapping — pure transform, no network."""

from ingestion.aprs_is_client import packet_to_event


def test_packet_to_event_with_weather_converts_to_imperial():
    # aprslib normalizes to metric: 32 °C, 5 mm rain, 10 m/s wind.
    packet = {
        "from": "N7XYZ-13",
        "latitude": 32.21,
        "longitude": -110.95,
        "symbol": "_",
        "comment": "Tucson weather station",
        "weather": {"temperature": 32.0, "rain_1h": 5.0, "wind_speed": 10.0},
    }
    event = packet_to_event(packet)
    assert event is not None
    assert event.callsign == "N7XYZ-13"
    assert event.symbol == "_"
    # 32 °C → 89.6 °F, 5 mm → ~0.197 in, 10 m/s → ~22.37 mph
    assert event.temp_f is not None and abs(event.temp_f - 89.6) < 0.05
    assert event.rainfall_in is not None and abs(event.rainfall_in - 0.1969) < 0.001
    assert event.wind_mph is not None and abs(event.wind_mph - 22.369) < 0.01


def test_packet_to_event_position_only():
    packet = {"from": "W7ABC", "latitude": 32.2, "longitude": -111.0}
    event = packet_to_event(packet)
    assert event is not None
    assert event.callsign == "W7ABC"
    assert event.temp_f is None


def test_packet_to_event_drops_no_callsign():
    assert packet_to_event({"latitude": 32, "longitude": -110}) is None


def test_packet_to_event_truncates_long_comment():
    long_comment = "x" * 1000
    event = packet_to_event({"from": "AB1CD", "comment": long_comment})
    assert event is not None
    assert len(event.comment) == 512
