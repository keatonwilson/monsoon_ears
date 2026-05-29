"""Activity-hold multi-frequency scanner with periodic NOAA visits.

The scanner is a state machine that wraps a `CaptureBackend` (production:
`AnalogCapture`; tests: a fake returning canned `CaptureChunk`s). It rotates
through a list of analog FM target frequencies, probes each one briefly using
the existing RMS-based squelch, and holds on whichever has signal until the
transmission ends (hangover) or a hard timeout fires.

NOAA Weather Radio is deliberately excluded from the scan list because it
broadcasts continuously — it would trip every probe and never release the
hold. Instead the scanner periodically suspends scanning to visit NOAA for a
short window, then resumes.

The single-dongle reality means we will *miss* some traffic on channels we
aren't tuned to. The plan accepts that loss in exchange for diverse coverage
across all priority frequencies.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

import numpy as np

from config.frequencies import Frequency
from ingestion.capture_analog import CaptureChunk

logger = logging.getLogger(__name__)


class CaptureBackend(Protocol):
    """Minimal interface required by FrequencyScanner."""

    def retune(self, freq_mhz: float) -> None: ...
    def read_chunk_full(self, duration_sec: float) -> CaptureChunk: ...
    def close(self) -> None: ...


@dataclass
class ActiveCapture:
    """A chunk that passed squelch — emitted by the scanner."""
    frequency: Frequency
    audio: np.ndarray
    audio_rms: float


# Synthesize a Frequency object for NOAA visits so downstream code has a
# consistent interface regardless of how the dongle got here.
_NOAA_FREQ_TEMPLATE = Frequency(
    name="NOAA Weather Radio (periodic visit)",
    mhz=162.3975,
    mode="nfm",
    agency="NOAA",
    priority="primary",
)


class FrequencyScanner:
    def __init__(
        self,
        backend: CaptureBackend,
        scan_frequencies: list[Frequency],
        noaa_freq_mhz: float | None = 162.3975,
        probe_sec: float = 1.0,
        hangover_chunks: int = 1,
        max_hold_sec: float = 120.0,
        noaa_visit_interval_min: float = 15.0,
        noaa_visit_duration_sec: float = 30.0,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        if not scan_frequencies:
            raise ValueError("scan_frequencies must not be empty")
        self.backend = backend
        self.scan_frequencies = scan_frequencies
        self.noaa_freq_mhz = noaa_freq_mhz
        self.probe_sec = probe_sec
        self.hangover_chunks = hangover_chunks
        self.max_hold_sec = max_hold_sec
        self.noaa_visit_interval_min = noaa_visit_interval_min
        self.noaa_visit_duration_sec = noaa_visit_duration_sec
        self._time = time_fn

        self._idx = 0
        self._holding = False
        self._hold_started_at: float | None = None
        self._hold_silence_count = 0
        self._last_noaa_visit = time_fn()  # don't visit NOAA on the first tick
        # Audio from the probe that triggered the current HOLD — prepended to the
        # first HOLD chunk so very short transmissions aren't lost in the silence
        # that follows the key-down. Cleared after one yield.
        self._pending_probe_audio: np.ndarray | None = None

    def _advance(self) -> None:
        self._idx = (self._idx + 1) % len(self.scan_frequencies)
        self._holding = False
        self._hold_started_at = None
        self._hold_silence_count = 0
        self._pending_probe_audio = None

    def _noaa_due(self) -> bool:
        if self.noaa_freq_mhz is None:
            return False
        return (self._time() - self._last_noaa_visit) >= self.noaa_visit_interval_min * 60

    def _visit_noaa(self, chunk_sec: float) -> Iterator[ActiveCapture]:
        logger.info("scanner: NOAA visit (%.4f MHz) for %.1fs",
                    self.noaa_freq_mhz, self.noaa_visit_duration_sec)
        self.backend.retune(self.noaa_freq_mhz)
        noaa_freq = Frequency(
            name=_NOAA_FREQ_TEMPLATE.name,
            mhz=self.noaa_freq_mhz,
            mode=_NOAA_FREQ_TEMPLATE.mode,
            agency=_NOAA_FREQ_TEMPLATE.agency,
            priority=_NOAA_FREQ_TEMPLATE.priority,
        )
        elapsed = 0.0
        while elapsed < self.noaa_visit_duration_sec:
            this_chunk_sec = min(chunk_sec, self.noaa_visit_duration_sec - elapsed)
            chunk = self.backend.read_chunk_full(this_chunk_sec)
            elapsed += this_chunk_sec
            if not chunk.squelched:
                yield ActiveCapture(noaa_freq, chunk.audio, chunk.audio_rms)
        self._last_noaa_visit = self._time()
        # Force a clean scan resume.
        self._holding = False
        self._hold_started_at = None
        self._hold_silence_count = 0

    def iter_active_chunks(self, chunk_sec: float) -> Iterator[ActiveCapture]:
        """Yield captures from frequencies that currently have signal."""
        while True:
            if self._noaa_due():
                yield from self._visit_noaa(chunk_sec)
                continue

            freq = self.scan_frequencies[self._idx]

            if not self._holding:
                self.backend.retune(freq.mhz)
                probe = self.backend.read_chunk_full(self.probe_sec)
                if probe.squelched:
                    logger.debug(
                        "scanner: probe %s (%.4f) silent rms=%.3f, advancing",
                        freq.name, freq.mhz, probe.audio_rms,
                    )
                    self._idx = (self._idx + 1) % len(self.scan_frequencies)
                    continue
                logger.info(
                    "scanner: HOLD on %s (%.4f) rms=%.3f",
                    freq.name, freq.mhz, probe.audio_rms,
                )
                self._holding = True
                self._hold_started_at = self._time()
                self._hold_silence_count = 0
                # Save the probe audio so the next HOLD chunk can prepend it.
                # Short transmissions are often entirely inside the probe — losing
                # this audio means losing the dispatch.
                self._pending_probe_audio = probe.audio
                continue

            # HOLD: max-time guard.
            if self._hold_started_at is not None and \
                    (self._time() - self._hold_started_at) > self.max_hold_sec:
                logger.info(
                    "scanner: HOLD timeout on %s after %.1fs, resuming scan",
                    freq.name, self.max_hold_sec,
                )
                self._advance()
                continue

            chunk = self.backend.read_chunk_full(chunk_sec)

            # If we have pending probe audio, the first HOLD yield always emits
            # (probe + this chunk), regardless of this chunk's squelch flag.
            # The probe alone is proof of recent signal; combining gives VAD
            # something substantial to work with.
            if self._pending_probe_audio is not None:
                combined = np.concatenate([self._pending_probe_audio, chunk.audio])
                self._pending_probe_audio = None
                logger.debug("scanner: yielding probe+chunk (%d samples)", combined.size)
                yield ActiveCapture(freq, combined, chunk.audio_rms)
                # If the post-probe chunk was squelched, treat it as one silent
                # tick — this freq is probably done.
                if chunk.squelched:
                    self._hold_silence_count = 1
                else:
                    self._hold_silence_count = 0
                continue

            if chunk.squelched:
                self._hold_silence_count += 1
                if self._hold_silence_count >= self.hangover_chunks:
                    logger.info(
                        "scanner: hangover hit on %s, resuming scan",
                        freq.name,
                    )
                    self._advance()
                continue

            self._hold_silence_count = 0
            yield ActiveCapture(freq, chunk.audio, chunk.audio_rms)
