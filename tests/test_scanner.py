"""Scanner state-machine tests using a fake CaptureBackend (no SDR needed)."""

from dataclasses import dataclass

import numpy as np
import pytest

from config.frequencies import Frequency
from ingestion.capture_analog import CaptureChunk
from ingestion.scanner import FrequencyScanner


def make_chunk(squelched: bool, rms: float = 0.5, n_samples: int = 16000) -> CaptureChunk:
    return CaptureChunk(
        audio=np.zeros(n_samples, dtype=np.float32),
        audio_rms=rms,
        iq_power=0.001,
        squelched=squelched,
    )


class ChunkScriptExhausted(Exception):
    """Raised by FakeBackend when the test script has no more chunks scheduled."""


@dataclass
class FakeBackend:
    """Returns canned CaptureChunks; records retune calls for assertions."""
    chunks: list[CaptureChunk]
    retunes: list[float]

    def __init__(self, chunk_script: list[CaptureChunk]):
        self.chunks = list(chunk_script)
        self.retunes = []

    def retune(self, freq_mhz: float) -> None:
        self.retunes.append(freq_mhz)

    def read_chunk_full(self, duration_sec: float) -> CaptureChunk:
        if not self.chunks:
            # Use a non-StopIteration to avoid PEP 479 turning it into RuntimeError
            # when raised inside the scanner's generator.
            raise ChunkScriptExhausted
        return self.chunks.pop(0)

    def close(self) -> None:
        pass


def _freqs() -> list[Frequency]:
    return [
        Frequency("A", 154.370, "nfm", "Rural Metro", "primary"),
        Frequency("B", 153.815, "nfm", "Rural Metro", "primary"),
        Frequency("C", 154.400, "nfm", "Rural Metro", "high"),
    ]


def _make_scanner(backend, **kwargs):
    """Helper: build a scanner with NOAA disabled by default."""
    defaults = dict(
        scan_frequencies=_freqs(),
        noaa_freq_mhz=None,         # disable NOAA visits for state-machine tests
        probe_sec=1.0,
        hangover_chunks=1,
        max_hold_sec=120.0,
        noaa_visit_interval_min=15.0,
        noaa_visit_duration_sec=30.0,
    )
    defaults.update(kwargs)
    return FrequencyScanner(backend=backend, **defaults)


def _take(gen, n):
    return [next(gen) for _ in range(n)]


def test_all_silent_no_yields_and_rotates():
    """Every probe squelched → never yields, retunes through all freqs."""
    backend = FakeBackend([make_chunk(squelched=True)] * 6)
    scanner = _make_scanner(backend)
    gen = scanner.iter_active_chunks(chunk_sec=15)
    with pytest.raises(ChunkScriptExhausted):
        next(gen)
    # 6 chunks consumed (all silent probes) → scanner advances and tries to probe
    # a 7th time before running out. Expect cycling through the 3-freq list.
    assert backend.retunes[:6] == [154.370, 153.815, 154.400, 154.370, 153.815, 154.400]


def test_signal_enters_hold_and_yields():
    """Probe finds signal on A → first hold yield is (probe + next chunk)."""
    backend = FakeBackend([
        make_chunk(squelched=False, rms=0.3, n_samples=16000),  # probe on A: signal (1s)
        make_chunk(squelched=False, rms=0.3, n_samples=240000), # hold read 1: yield
        make_chunk(squelched=True),                              # hold read 2: hangover
        make_chunk(squelched=True),                              # scan B: silent
        make_chunk(squelched=True),                              # scan C: silent
    ])
    scanner = _make_scanner(backend)
    gen = scanner.iter_active_chunks(chunk_sec=15)
    cap = next(gen)
    assert cap.frequency.name == "A"
    # Probe (16000 samples) prepended to chunk (240000 samples) = 256000 total.
    assert cap.audio.size == 16000 + 240000
    # Next iteration: hangover hits → scan B, C; both silent → ChunkScriptExhausted.
    with pytest.raises(ChunkScriptExhausted):
        next(gen)


def test_probe_prepended_only_on_first_hold_chunk():
    """After the first yield, subsequent HOLD chunks should not have the probe."""
    backend = FakeBackend([
        make_chunk(squelched=False, rms=0.3, n_samples=16000),  # probe
        make_chunk(squelched=False, rms=0.3, n_samples=240000), # 1st HOLD yield (prepended)
        make_chunk(squelched=False, rms=0.3, n_samples=240000), # 2nd HOLD yield (not prepended)
        make_chunk(squelched=True),
        make_chunk(squelched=True),
        make_chunk(squelched=True),
    ])
    scanner = _make_scanner(backend)
    gen = scanner.iter_active_chunks(chunk_sec=15)
    first = next(gen)
    second = next(gen)
    assert first.audio.size == 16000 + 240000
    assert second.audio.size == 240000  # no probe prefix


def test_hangover_takes_multiple_squelched_chunks():
    """With hangover_chunks=2, hold doesn't release until 2 consecutive squelches."""
    backend = FakeBackend([
        make_chunk(squelched=False),  # probe A: signal
        make_chunk(squelched=False),  # hold read 1: yield
        make_chunk(squelched=True),   # squelch 1 — still holding
        make_chunk(squelched=False),  # signal again — yield, reset counter
        make_chunk(squelched=True),   # squelch 1
        make_chunk(squelched=True),   # squelch 2 → release
        make_chunk(squelched=True),   # scan B: silent
        make_chunk(squelched=True),   # scan C: silent
    ])
    scanner = _make_scanner(backend, hangover_chunks=2)
    gen = scanner.iter_active_chunks(chunk_sec=15)
    caps = _take(gen, 2)
    assert all(c.frequency.name == "A" for c in caps)
    with pytest.raises(ChunkScriptExhausted):
        next(gen)


def test_max_hold_sec_force_releases():
    """Even with continuous signal, max_hold_sec forces a scan resume."""
    fake_time = [0.0]

    def time_fn():
        return fake_time[0]

    backend = FakeBackend([
        make_chunk(squelched=False),  # probe A: signal
        make_chunk(squelched=False),  # hold read 1: yield — advance clock
        # After this point the next iteration sees clock > max_hold_sec
        make_chunk(squelched=True),   # scan B: silent
        make_chunk(squelched=True),   # scan C: silent
    ])
    scanner = _make_scanner(backend, max_hold_sec=10.0, time_fn=time_fn)
    gen = scanner.iter_active_chunks(chunk_sec=15)
    cap = next(gen)
    assert cap.frequency.name == "A"
    # Push the clock past the timeout — scanner should bail next iteration.
    fake_time[0] = 100.0
    with pytest.raises(ChunkScriptExhausted):
        next(gen)
    # Confirm we ended up retuning to B (next freq) after force-release.
    assert 153.815 in backend.retunes


def test_periodic_noaa_visit_yields_then_resumes():
    """When NOAA is due, scanner suspends scan, visits NOAA, yields, resumes."""
    fake_time = [0.0]

    def time_fn():
        return fake_time[0]

    backend = FakeBackend([
        make_chunk(squelched=False, rms=0.27),  # NOAA chunk 1 (30s → one chunk)
        make_chunk(squelched=True),             # scan A: silent
        make_chunk(squelched=True),             # scan B: silent
        make_chunk(squelched=True),             # scan C: silent
    ])
    scanner = FrequencyScanner(
        backend=backend,
        scan_frequencies=_freqs(),
        noaa_freq_mhz=162.3975,
        noaa_visit_interval_min=15.0,
        noaa_visit_duration_sec=30.0,
        probe_sec=1.0,
        hangover_chunks=1,
        max_hold_sec=120.0,
        time_fn=time_fn,
    )
    # Trip the "NOAA overdue" condition on the very first iteration.
    fake_time[0] = 16 * 60
    gen = scanner.iter_active_chunks(chunk_sec=30)
    cap = next(gen)
    assert cap.frequency.mhz == 162.3975
    assert cap.frequency.agency == "NOAA"
    # After NOAA, scanner resumes scanning A/B/C → all silent → StopIteration.
    with pytest.raises(ChunkScriptExhausted):
        next(gen)
    # First retune should have been to NOAA.
    assert backend.retunes[0] == 162.3975
