"""In-process NFM capture from RTL-SDR via pyrtlsdr.

Pulls IQ samples at the SDR's native rate, decimates to an intermediate
baseband rate, performs FM demodulation, then decimates again to a Whisper-
friendly audio rate (default 16 kHz mono float32).

Squelch is a simple RMS threshold on the demodulated audio — if the chunk is
below `silence_threshold`, `read_chunk` returns None and the caller skips it.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

import numpy as np
from scipy.signal import decimate

logger = logging.getLogger(__name__)


class AnalogCapture:
    def __init__(
        self,
        freq_mhz: float,
        sample_rate: int = 1_024_000,
        intermediate_rate: int = 64_000,
        audio_rate: int = 16_000,
        gain: float | str = 40.0,
        silence_threshold: float = 0.01,
    ):
        # Lazy import so unit tests on Mac don't need librtlsdr installed.
        from rtlsdr import RtlSdr

        self.freq_mhz = freq_mhz
        self.sample_rate = sample_rate
        self.intermediate_rate = intermediate_rate
        self.audio_rate = audio_rate
        self.silence_threshold = silence_threshold

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
            "RTL-SDR tuned to %.4f MHz, sr=%d, gain=%s, decim=%dx%d",
            freq_mhz, sample_rate, gain, self._decim1, self._decim2,
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

    def read_chunk(self, duration_sec: float) -> Optional[np.ndarray]:
        """Read one chunk of demodulated audio. Returns None if below squelch."""
        n_samples = int(self.sample_rate * duration_sec)
        # pyrtlsdr requires a multiple of 512.
        n_samples = (n_samples // 512) * 512
        iq = self.sdr.read_samples(n_samples)

        # Stage 1: decimate complex baseband to intermediate rate.
        iq_baseband = decimate(iq, self._decim1, ftype="fir", zero_phase=True)

        # Quadrature FM demodulation.
        demod = np.angle(iq_baseband[1:] * np.conj(iq_baseband[:-1]))

        # Stage 2: decimate to audio rate.
        audio = decimate(demod, self._decim2, ftype="fir", zero_phase=True).astype(np.float32)

        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < self.silence_threshold:
            logger.debug("squelched chunk rms=%.5f < %.5f", rms, self.silence_threshold)
            return None
        logger.debug("captured chunk rms=%.5f len=%d", rms, audio.size)
        return audio

    def iter_chunks(self, duration_sec: float) -> Iterator[Optional[np.ndarray]]:
        while True:
            yield self.read_chunk(duration_sec)
