"""In-process NFM capture from RTL-SDR via pyrtlsdr.

Pulls IQ samples at the SDR's native rate, decimates to an intermediate
baseband rate, performs FM demodulation, then decimates again to a Whisper-
friendly audio rate (default 16 kHz mono float32).

Squelch is **inverted-RMS on the demodulated audio.** A quadrature FM demod
fed pure noise produces near-uniform output in [-π, π] with high RMS
(~0.85+ in practice). A demod fed an actual carrier produces voice-shaped
output with much lower RMS (~0.25–0.4 observed on NOAA). The RTL-SDR's AGC
flattens IQ-domain power, so pre-demod power can't tell signal from noise —
only the demod output structure can. Hence: PASS when audio_rms is *below*
`noise_floor_rms`, squelch when above.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np
from scipy.signal import decimate

logger = logging.getLogger(__name__)


@dataclass
class CaptureChunk:
    audio: np.ndarray            # demodulated 16 kHz mono float32
    audio_rms: float             # post-demod RMS (the squelch metric)
    iq_power: float              # mean |iq|^2 (informational; AGC flattens it)
    squelched: bool              # True if audio_rms >= noise_floor_rms


class AnalogCapture:
    def __init__(
        self,
        freq_mhz: float,
        sample_rate: int = 1_024_000,
        intermediate_rate: int = 64_000,
        audio_rate: int = 16_000,
        gain: float | str = 40.0,
        noise_floor_rms: float = 0.65,
    ):
        # Lazy import so unit tests on Mac don't need librtlsdr installed.
        from rtlsdr import RtlSdr

        self.freq_mhz = freq_mhz
        self.sample_rate = sample_rate
        self.intermediate_rate = intermediate_rate
        self.audio_rate = audio_rate
        self.noise_floor_rms = noise_floor_rms

        if sample_rate % intermediate_rate != 0:
            raise ValueError(
                f"sample_rate ({sample_rate}) must be an integer multiple of "
                f"intermediate_rate ({intermediate_rate})"
            )
        if intermediate_rate % audio_rate != 0:
            raise ValueError(
                f"intermediate_rate ({intermediate_rate}) must be an integer "
                f"multiple of audio_rate ({audio_rate})"
            )
        self._decim1 = sample_rate // intermediate_rate
        self._decim2 = intermediate_rate // audio_rate

        self.sdr = RtlSdr()
        self.sdr.sample_rate = sample_rate
        self.sdr.center_freq = int(freq_mhz * 1e6)
        self.sdr.gain = gain
        logger.info(
            "RTL-SDR tuned to %.4f MHz, sr=%d, gain=%s, decim=%dx%d, "
            "noise_floor_rms=%.3f",
            freq_mhz, sample_rate, gain, self._decim1, self._decim2,
            noise_floor_rms,
        )

    def close(self) -> None:
        try:
            self.sdr.close()
        except Exception:  # noqa: BLE001 - device may already be closed
            pass

    def __enter__(self) -> "AnalogCapture":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def read_chunk_full(self, duration_sec: float) -> CaptureChunk:
        """Read one chunk with full diagnostics. Squelched flag set, never None."""
        n_samples = int(self.sample_rate * duration_sec)
        n_samples = (n_samples // 512) * 512  # pyrtlsdr needs multiple of 512
        iq = self.sdr.read_samples(n_samples)

        iq_power = float(np.mean(np.abs(iq) ** 2))

        # Stage 1: decimate complex baseband to intermediate rate.
        iq_baseband = decimate(iq, self._decim1, ftype="fir", zero_phase=True)

        # Quadrature FM demodulation.
        demod = np.angle(iq_baseband[1:] * np.conj(iq_baseband[:-1]))

        # Stage 2: decimate to audio rate.
        audio = decimate(demod, self._decim2, ftype="fir", zero_phase=True).astype(np.float32)
        audio_rms = float(np.sqrt(np.mean(audio ** 2)))

        squelched = audio_rms >= self.noise_floor_rms
        logger.debug(
            "chunk audio_rms=%.4f iq_power=%.5f %s",
            audio_rms, iq_power, "SQUELCHED" if squelched else "PASS",
        )
        return CaptureChunk(audio=audio, audio_rms=audio_rms, iq_power=iq_power, squelched=squelched)

    def read_chunk(self, duration_sec: float) -> Optional[np.ndarray]:
        """Convenience: return audio array or None if squelched."""
        chunk = self.read_chunk_full(duration_sec)
        return None if chunk.squelched else chunk.audio

    def iter_chunks(self, duration_sec: float) -> Iterator[Optional[np.ndarray]]:
        while True:
            yield self.read_chunk(duration_sec)
