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
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional, Protocol

import numpy as np

logger = logging.getLogger(__name__)

WHISPER_SR = 16_000
# op25 voice audio is natively 8 kHz, signed-16-bit, mono, little-endian.
OP25_AUDIO_SR = 8_000

# op25 per-call WAV filename contract: "<talkgroup_dec>-<epoch_millis>.wav".
# The runbook configures op25's call recorder to write files this way.
_WAV_NAME_RE = re.compile(r"^(?P<tgid>\d+)-(?P<epoch_ms>\d+)\.wav$")


@dataclass(frozen=True)
class P25Call:
    """One decoded voice transmission handed off by op25."""
    audio: np.ndarray       # mono float32, WHISPER_SR
    sample_rate: int
    talkgroup_id: Optional[int]   # None if op25's console didn't name one in time
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


# --- UDP backend (the real op25 `-U` path) ----------------------------------
#
# Live finding (deploy/op25_setup.md §4): with `-U`, op25 does NOT write per-call
# WAVs — it streams decoded voice as raw 16-bit PCM over UDP to 127.0.0.1:23456,
# and exposes the *current* call's talkgroup via its :8080 HTTP console (the same
# JSON the web UI polls). So a call boundary is an inter-packet gap in the UDP
# stream; the talkgroup is whatever the console reported during that call.
#
# The pure pieces below (PCM decode, console-message parsing, call segmentation)
# are unit-tested; the socket/HTTP/thread shell in `UdpP25Backend` is what needs
# live validation on the Pi.


def pcm_bytes_to_float32(buf: bytes) -> np.ndarray:
    """Decode raw little-endian int16 mono PCM into float32 in [-1, 1]. Pure."""
    if not buf:
        return np.zeros(0, dtype=np.float32)
    # Drop a trailing odd byte (a partial sample) defensively.
    if len(buf) % 2:
        buf = buf[:-1]
    samples = np.frombuffer(buf, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def parse_active_tgid(messages) -> Optional[int]:
    """Pull the active voice talkgroup from an op25 console JSON response. Pure.

    op25's HTTP console returns a list of message dicts; a voice grant shows up
    as a `change_freq` message carrying `tgid` (and `tag`). We prefer the last
    `change_freq`, then fall back to any message exposing a positive `tgid`.
    Tolerant of shape drift — returns None if nothing usable is present.
    """
    if not isinstance(messages, list):
        return None
    fallback: Optional[int] = None
    chosen: Optional[int] = None
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        tg = msg.get("tgid")
        try:
            tg = int(tg) if tg is not None else None
        except (TypeError, ValueError):
            tg = None
        if not tg or tg <= 0:
            continue
        if msg.get("json_type") == "change_freq":
            chosen = tg
        fallback = tg
    return chosen if chosen is not None else fallback


@dataclass
class CallAccumulator:
    """Segment a gapped PCM stream into calls. Pure (caller supplies the clock).

    Feed it (timestamp, pcm_float32) as datagrams arrive and a current talkgroup;
    when more than `gap_sec` elapses with no audio, `flush_if_idle(now)` returns
    the completed call's (audio, tgid, started_at) and resets. The talkgroup
    assigned is the one active when the call *started* (the grant that opened it).
    """

    gap_sec: float = 0.8
    _buf: list[np.ndarray] = None  # type: ignore[assignment]
    _last_audio_t: Optional[float] = None
    _call_tgid: Optional[int] = None
    _started_at: Optional[float] = None

    def __post_init__(self):
        self._buf = []

    def feed(self, now: float, pcm: np.ndarray, tgid: Optional[int]) -> None:
        if pcm.size == 0:
            return
        if not self._buf:  # opening a new call
            self._started_at = now
            self._call_tgid = tgid
        elif self._call_tgid is None and tgid is not None:
            # Console caught up mid-call — adopt the first tgid we learn.
            self._call_tgid = tgid
        self._buf.append(pcm)
        self._last_audio_t = now

    def flush_if_idle(self, now: float) -> Optional[tuple[np.ndarray, Optional[int], float]]:
        if not self._buf or self._last_audio_t is None:
            return None
        if (now - self._last_audio_t) < self.gap_sec:
            return None
        audio = np.concatenate(self._buf)
        started = self._started_at if self._started_at is not None else now
        out = (audio, self._call_tgid, started)
        self._buf = []
        self._last_audio_t = None
        self._call_tgid = None
        self._started_at = None
        return out


class Op25ConsolePoller:
    """Background poller of op25's :8080 HTTP console for the active talkgroup."""

    def __init__(self, base_url: str, interval_sec: float = 0.4):
        self.base_url = base_url.rstrip("/")
        self.interval_sec = interval_sec
        self._tgid: Optional[int] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def tgid(self) -> Optional[int]:
        return self._tgid

    def _poll_once(self) -> None:
        import requests

        try:
            resp = requests.post(
                f"{self.base_url}/",
                json=[{"command": "update", "arg1": 0, "arg2": 0}],
                timeout=2,
            )
            resp.raise_for_status()
            tg = parse_active_tgid(resp.json())
            if tg is not None:
                self._tgid = tg
        except Exception as exc:  # noqa: BLE001 — console may blip; keep last tgid
            logger.debug("op25 console poll failed: %s", exc)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.interval_sec)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="op25-console", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


class UdpP25Backend:
    """Read op25's UDP PCM stream and yield one P25Call per voice transmission.

    Pairs each call with the talkgroup reported by op25's HTTP console. Replaces
    WavDirBackend for the `-U` op25 setup; everything downstream is unchanged.
    """

    def __init__(
        self,
        udp_host: str = "127.0.0.1",
        udp_port: int = 23456,
        console_url: Optional[str] = "http://127.0.0.1:8080",
        src_sample_rate: int = OP25_AUDIO_SR,
        gap_sec: float = 0.8,
        recv_bytes: int = 32768,
    ):
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.src_sample_rate = src_sample_rate
        self.gap_sec = gap_sec
        self.recv_bytes = recv_bytes
        self._closed = False
        self._sock: Optional[socket.socket] = None
        self._poller = Op25ConsolePoller(console_url) if console_url else None

    def close(self) -> None:
        self._closed = True
        if self._poller:
            self._poller.stop()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _emit(self, audio_src: np.ndarray, tgid: Optional[int], started_at: float) -> P25Call:
        audio = _resample_to_16k(audio_src, self.src_sample_rate)
        return P25Call(
            audio=audio,
            sample_rate=WHISPER_SR,
            talkgroup_id=tgid,
            timestamp=datetime.now(timezone.utc),
        )

    def iter_calls(self) -> Iterator[P25Call]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.udp_host, self.udp_port))
        # Wake periodically so we can detect the inter-call gap even with no data.
        sock.settimeout(min(self.gap_sec, 0.5))
        self._sock = sock
        if self._poller:
            self._poller.start()
        logger.info("UdpP25Backend listening on %s:%d (console=%s)",
                    self.udp_host, self.udp_port, bool(self._poller))

        acc = CallAccumulator(gap_sec=self.gap_sec)
        while not self._closed:
            now = time.monotonic()
            try:
                data, _ = sock.recvfrom(self.recv_bytes)
                tgid = self._poller.tgid if self._poller else None
                acc.feed(time.monotonic(), pcm_bytes_to_float32(data), tgid)
            except socket.timeout:
                pass
            except OSError:
                break  # socket closed by close()
            done = acc.flush_if_idle(time.monotonic())
            if done is not None:
                audio_src, tgid, started = done
                yield self._emit(audio_src, tgid, started)
        # Drain a final in-flight call on shutdown.
        done = acc.flush_if_idle(time.monotonic() + self.gap_sec + 1)
        if done is not None:
            audio_src, tgid, started = done
            yield self._emit(audio_src, tgid, started)


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
