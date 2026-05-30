"""P25 capture/runner tests — fake op25 backend, no SDR, no Whisper, no real DB."""

from datetime import datetime, timezone

import numpy as np

from ingestion.capture_p25 import (
    WHISPER_SR,
    P25Call,
    WavDirBackend,
    _resample_to_16k,
    run_p25_ingestion,
)


class FakeBackend:
    """Yields a canned list of P25Calls, then stops."""

    def __init__(self, calls):
        self._calls = calls
        self.closed = False

    def iter_calls(self):
        yield from self._calls

    def close(self):
        self.closed = True


def _call(tgid: int, *, seconds: float = 2.0) -> P25Call:
    n = int(seconds * WHISPER_SR)
    return P25Call(
        audio=np.zeros(n, dtype=np.float32),
        sample_rate=WHISPER_SR,
        talkgroup_id=tgid,
        timestamp=datetime.now(timezone.utc),
    )


def test_run_ingestion_writes_p25_rows_with_talkgroup():
    calls = [_call(15001), _call(13007)]
    inserted = []

    def fake_transcribe(audio, sr):
        return "Engine 1 responding to a structure fire"

    def fake_insert(event):
        inserted.append(event)
        return len(inserted)

    n = run_p25_ingestion(
        FakeBackend(calls),
        transcribe_fn=fake_transcribe,
        insert_fn=fake_insert,
    )

    assert n == 2
    assert [e.talkgroup_id for e in inserted] == [15001, 13007]
    assert all(e.source == "p25" for e in inserted)
    assert all(e.frequency_mhz == 0.0 for e in inserted)


def test_run_ingestion_skips_empty_transcripts_and_short_calls():
    calls = [_call(15001, seconds=0.3), _call(15001, seconds=2.0)]
    inserted = []

    # First call is too short (skipped before transcribe); second returns empty.
    def fake_transcribe(audio, sr):
        return ""  # hallucination/empty -> dropped

    n = run_p25_ingestion(
        FakeBackend(calls),
        transcribe_fn=fake_transcribe,
        insert_fn=lambda e: inserted.append(e) or 1,
    )
    assert n == 0
    assert inserted == []


def test_resample_to_16k_changes_length_proportionally():
    audio_8k = np.zeros(8000, dtype=np.float32)  # 1 second at 8 kHz
    out = _resample_to_16k(audio_8k, 8000)
    assert out.dtype == np.float32
    assert abs(out.size - 16000) <= 1  # ~1 second at 16 kHz


def test_resample_noop_at_16k():
    audio = np.ones(1600, dtype=np.float32)
    out = _resample_to_16k(audio, WHISPER_SR)
    assert out.size == 1600


def test_wavdir_backend_parses_talkgroup_and_yields(tmp_path):
    """Drop op25-style WAVs in a dir; backend reads, resamples, and yields calls."""
    from scipy.io import wavfile

    # Two valid call files (8 kHz int16) + one bad name that must be ignored.
    sr = 8000
    tone = (np.sin(np.linspace(0, 100, sr)) * 16000).astype(np.int16)
    wavfile.write(tmp_path / "15001-1700000000000.wav", sr, tone)
    wavfile.write(tmp_path / "13007-1700000001000.wav", sr, tone)
    (tmp_path / "garbage.wav").write_bytes(b"not a wav")

    backend = WavDirBackend(tmp_path, poll_sec=0.01)
    seen = []
    for call in backend.iter_calls():
        seen.append(call)
        if len(seen) == 2:
            backend.close()  # stop after we've consumed the two valid files

    tgids = sorted(c.talkgroup_id for c in seen)
    assert tgids == [13007, 15001]
    assert all(c.sample_rate == WHISPER_SR for c in seen)
    # Processed files are consumed (deleted); the bad-name file is left alone.
    assert not (tmp_path / "15001-1700000000000.wav").exists()
    assert (tmp_path / "garbage.wav").exists()
