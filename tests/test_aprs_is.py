"""packet_to_event mapping — pure transform, no network."""

from ingestion.aprs_is_client import packet_to_event


def test_packet_to_event_with_weather():
    packet = {
        "from": "N7XYZ-13",
        "latitude": 32.21,
        "longitude": -110.95,
        "symbol": "_",
        "comment": "Tucson weather station",
        "weather": {"temperature": 89.5, "rain_1h": 0.05, "wind_speed": 8},
    }
    event = packet_to_event(packet)
    assert event is not None
    assert event.callsign == "N7XYZ-13"
    assert event.lat == 32.21
    assert event.lon == -110.95
    assert event.symbol == "_"
    assert event.comment == "Tucson weather station"
    assert event.temp_f == 89.5
    assert event.rainfall_in == 0.05
    assert event.wind_mph == 8


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
