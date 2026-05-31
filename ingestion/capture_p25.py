"""P25 (PCWIN) capture scaffold — op25 decodes, we transcribe.

Unlike the analog path, there is no squelch/VAD/scanner here: op25 locks the
PCWIN control channel, follows voice grants on the whitelisted talkgroups (see
`config/op25/`), and emits *already-decoded* per-call voice audio tagged with
the talkgroup it came from. Our job is just to turn each decoded call into a
`TranscriptionEvent(source="p25", talkgroup_id=...)` via the same Whisper path
the analog runner uses.

The op25 ↔ Python boundary is isolated behind the `P25Backend` protocol so the
ingestion loop is fully unit-testable with a fake backend (mirrors how
`ingestion/scanner.py` injects its capture backend). The concrete
`WavDirBackend` below — which bridges a real op25 process — is the only part
that needs on-Pi RF validation; see `deploy/op25_setup.md`.

⚠️ The WavDirBackend has NOT been validated against a live op25 decode (that
requires the Pi + SDR + a built op25). Treat it as a scaffold: the file-naming
contract and resampling are defined here, but confirm them on the Pi.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional, Protocol

import numpy as np

logger = logging.getLogger(__name__)

WHISPER_SR = 16_000

# op25 per-call WAV filename contract: "<talkgroup_dec>-<epoch_millis>.wav".
# The runbook configures op25's call recorder to write files this way.
_WAV_NAME_RE = re.compile(r"^(?P<tgid>\d+)-(?P<epoch_ms>\d+)\.wav$")


@dataclass(frozen=True)
class P25Call:
    """One decoded voice transmission handed off by op25."""
    audio: np.ndarray       # mono float32, WHISPER_SR
    sample_rate: int
    talkgroup_id: int
    timestamp: datetime


class P25Backend(Protocol):
    """Source of decoded P25 calls. Inject a fake in tests."""

    def iter_calls(self) -> Iterator[P25Call]:
        ...

    def close(self) -> None:
        ...


def _resample_to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    """Linear resample to 16 kHz mono float32. op25 voice is natively 8 kHz."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr == WHISPER_SR:
        return audio
    if audio.size == 0:
        return audio
    duration = audio.size / sr
    n_out = int(round(duration * WHISPER_SR))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class WavDirBackend:
    """Watch a directory op25 writes per-call WAVs into and yield them as calls.

    Files must be named `<talkgroup_dec>-<epoch_millis>.wav`. Each file is read,
    resampled to 16 kHz, yielded, then deleted. Polls until `close()` is called.

    ⚠️ Unvalidated against a live op25 — see module docstring.
    """

    def __init__(self, watch_dir: str | Path, poll_sec: float = 1.0):
        self.watch_dir = Path(watch_dir)
        self.poll_sec = poll_sec
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _read_wav(self, path: Path) -> tuple[np.ndarray, int]:
        from scipy.io import wavfile  # local import; scipy only needed on the Pi

        sr, data = wavfile.read(path)
        data = np.asarray(data)
        # Normalize integer PCM to float32 in [-1, 1].
        if np.issubdtype(data.dtype, np.integer):
            max_val = float(np.iinfo(data.dtype).max)
            data = data.astype(np.float32) / max_val
        else:
            data = data.astype(np.float32)
        return data, int(sr)

    def iter_calls(self) -> Iterator[P25Call]:
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        while not self._closed:
            wavs = sorted(self.watch_dir.glob("*.wav"))
            if not wavs:
                time.sleep(self.poll_sec)
                continue
            for path in wavs:
                m = _WAV_NAME_RE.match(path.name)
                if not m:
                    logger.warning("ignoring op25 wav with unexpected name: %s", path.name)
                    continue
                try:
                    data, sr = self._read_wav(path)
                    audio = _resample_to_16k(data, sr)
                    ts = datetime.fromtimestamp(int(m["epoch_ms"]) / 1000, tz=timezone.utc)
                    yield P25Call(
                        audio=audio,
                        sample_rate=WHISPER_SR,
                        talkgroup_id=int(m["tgid"]),
                        timestamp=ts,
                    )
                except Exception:  # noqa: BLE001 — a bad file must not kill the loop
                    logger.exception("failed to read op25 wav %s", path)
                finally:
                    path.unlink(missing_ok=True)


# --- Ingestion loop ----------------------------------------------------------

# Injection points kept as module attributes so tests can monkeypatch them and
# the runner can be exercised without Whisper or a real DB.
def _default_transcribe(audio: np.ndarray, sr: int) -> Optional[str]:
    from ingestion.transcribe import transcribe
    return transcribe(audio, sr=sr)


def _default_insert(event) -> int:
    from db.queries import insert_transcription
    return insert_transcription(event)


def run_p25_ingestion(
    backend: P25Backend,
    *,
    transcribe_fn: Callable[[np.ndarray, int], Optional[str]] = _default_transcribe,
    insert_fn: Callable[[object], int] = _default_insert,
    min_duration_sec: float = 1.0,
) -> int:
    """Consume decoded calls from `backend`, transcribe, and store as p25 rows.

    Returns the number of rows inserted (handy for tests). Runs until the
    backend's `iter_calls()` stops yielding (e.g. after `close()`).
    """
    from models.schemas import TranscriptionEvent

    inserted = 0
    for call in backend.iter_calls():
        duration_sec = call.audio.size / call.sample_rate if call.sample_rate else 0.0
        if duration_sec < min_duration_sec:
            logger.debug("skipping <%.1fs p25 call on tg %d", min_duration_sec, call.talkgroup_id)
            continue
        text = transcribe_fn(call.audio, call.sample_rate)
        if not text:
            continue
        event = TranscriptionEvent(
            timestamp=call.timestamp,
            frequency_mhz=0.0,  # trunked: the talkgroup, not a frequency, identifies the channel
            raw_text=text,
            duration_sec=duration_sec,
            source="p25",
            talkgroup_id=call.talkgroup_id,
        )
        row_id = insert_fn(event)
        inserted += 1
        logger.info("[p25 tg=%d] id=%s (%.1fs) %s", call.talkgroup_id, row_id, duration_sec, text[:120])
    return inserted
