"""UDP P25 backend pure logic: PCM decode, console parsing, call segmentation."""

import numpy as np

from ingestion.capture_p25 import (
    CallAccumulator,
    P25Call,
    pcm_bytes_to_float32,
    parse_active_tgid,
    run_p25_ingestion,
)


# --- PCM decode --------------------------------------------------------------


def test_pcm_bytes_to_float32_scales_int16():
    raw = np.array([0, 32767, -32768, 16384], dtype="<i2").tobytes()
    out = pcm_bytes_to_float32(raw)
    assert out.dtype == np.float32
    assert out[0] == 0.0
    assert abs(out[1] - 1.0) < 1e-3
    assert abs(out[2] + 1.0) < 1e-3


def test_pcm_bytes_handles_empty_and_odd_length():
    assert pcm_bytes_to_float32(b"").size == 0
    # Odd trailing byte (partial sample) is dropped, not crashed on.
    assert pcm_bytes_to_float32(b"\x01\x00\x7f").size == 1


# --- console talkgroup parsing -----------------------------------------------


def test_parse_active_tgid_prefers_change_freq():
    msgs = [
        {"json_type": "trunk_update", "tgid": 11012},
        {"json_type": "change_freq", "tgid": 15001, "tag": "TFD A2"},
    ]
    assert parse_active_tgid(msgs) == 15001


def test_parse_active_tgid_fallback_and_none():
    assert parse_active_tgid([{"json_type": "rx_update", "tgid": 13003}]) == 13003
    assert parse_active_tgid([{"json_type": "rx_update"}]) is None
    assert parse_active_tgid([{"json_type": "change_freq", "tgid": 0}]) is None
    assert parse_active_tgid("not a list") is None


# --- call segmentation -------------------------------------------------------


def _pcm(n: int) -> np.ndarray:
    return np.full(n, 0.1, dtype=np.float32)


def test_accumulator_flushes_on_gap_with_call_tgid():
    acc = CallAccumulator(gap_sec=0.8)
    # Audio arrives at t=0 and t=0.1 while tg 15001 is active.
    acc.feed(0.0, _pcm(800), 15001)
    acc.feed(0.1, _pcm(800), 15001)
    # No gap yet.
    assert acc.flush_if_idle(0.5) is None
    # Gap exceeded -> emit the call tagged with the opening tgid.
    out = acc.flush_if_idle(1.0)
    assert out is not None
    audio, tgid, started = out
    assert audio.size == 1600
    assert tgid == 15001
    assert started == 0.0
    # Buffer reset.
    assert acc.flush_if_idle(2.0) is None


def test_accumulator_adopts_late_tgid_and_separates_calls():
    acc = CallAccumulator(gap_sec=0.5)
    # Call opens before the console knows the tgid; it's adopted mid-call.
    acc.feed(0.0, _pcm(400), None)
    acc.feed(0.1, _pcm(400), 15006)
    out1 = acc.flush_if_idle(1.0)
    assert out1[1] == 15006
    # A second, separate call with a different tgid.
    acc.feed(2.0, _pcm(400), 13007)
    out2 = acc.flush_if_idle(3.0)
    assert out2[1] == 13007


# --- ingestion loop integration (fake backend) -------------------------------


class _FakeBackend:
    def __init__(self, calls):
        self._calls = calls

    def iter_calls(self):
        yield from self._calls

    def close(self):
        pass


def test_run_p25_ingestion_passes_tgid_through(monkeypatch):
    from datetime import datetime, timezone

    call = P25Call(
        audio=np.full(16000, 0.1, dtype=np.float32),  # 1.0s @ 16k
        sample_rate=16000, talkgroup_id=15001,
        timestamp=datetime.now(timezone.utc),
    )
    seen = {}

    def fake_insert(event):
        seen["source"] = event.source
        seen["tgid"] = event.talkgroup_id
        return 1

    n = run_p25_ingestion(
        _FakeBackend([call]),
        transcribe_fn=lambda audio, sr: "engine 7 responding",
        insert_fn=fake_insert,
        min_duration_sec=0.5,
    )
    assert n == 1
    assert seen == {"source": "p25", "tgid": 15001}
