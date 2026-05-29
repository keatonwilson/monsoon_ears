"""Voice Activity Detection (WebRTC VAD) for segmenting captured chunks.

WebRTC VAD makes binary speech/non-speech decisions on 10/20/30ms frames of
16-bit PCM audio at 8/16/32/48 kHz. We use 30ms frames at 16 kHz (480 samples)
because larger frames are more robust to brief noise spikes.

The segmenter applies two rounds of hysteresis to convert raw frame decisions
into clean speech segments:

    1. Merge segments separated by gaps shorter than `merge_gap_ms`
       (typical inter-word pauses are 100–300ms — we don't want to split
       on those).
    2. Drop segments shorter than `min_segment_ms` (transient noise, key-up
       blips that pass the squelch but aren't real speech).

Aggressiveness 0 = least aggressive about flagging non-speech as speech
(fewer false positives), 3 = most aggressive (more false positives but won't
miss quiet speech). We default to 2 because radio audio is noisy and lower
settings tend to mark voice-band noise as speech.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

FRAME_MS = 30  # supported: 10, 20, 30
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480


@dataclass
class SpeechSegment:
    start_sample: int
    end_sample: int

    def duration_ms(self) -> int:
        return int((self.end_sample - self.start_sample) * 1000 / SAMPLE_RATE)


def _float_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 audio in [-1, 1] to little-endian int16 PCM bytes."""
    pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


def _flags_to_segments(flags: list[bool]) -> list[tuple[int, int]]:
    """Collapse per-frame flags into (start_frame, end_frame) half-open runs."""
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for i, is_speech in enumerate(flags):
        if is_speech and start is None:
            start = i
        elif not is_speech and start is not None:
            segments.append((start, i))
            start = None
    if start is not None:
        segments.append((start, len(flags)))
    return segments


def _merge_close(segments: list[tuple[int, int]], max_gap_frames: int) -> list[tuple[int, int]]:
    if not segments:
        return []
    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap_frames:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def find_speech_segments(
    audio: np.ndarray,
    aggressiveness: int = 2,
    merge_gap_ms: int = 300,
    min_segment_ms: int = 500,
    pad_ms: int = 200,
) -> list[SpeechSegment]:
    """Locate speech regions inside a chunk.

    `audio` must be mono float32 at 16 kHz. Returned segments are in sample
    indices (relative to the input array), with `pad_ms` of padding added on
    each side and clamped to the buffer length.
    """
    if audio is None or len(audio) < FRAME_SAMPLES:
        return []

    n_frames = len(audio) // FRAME_SAMPLES
    # Classify each frame (need raw list, _flags_to_segments needs to iterate twice).
    flags: list[bool] = []
    pcm = _float_to_pcm16(audio[: n_frames * FRAME_SAMPLES])
    bytes_per_frame = FRAME_SAMPLES * 2
    import webrtcvad
    vad = webrtcvad.Vad(aggressiveness)
    for i in range(n_frames):
        frame = pcm[i * bytes_per_frame : (i + 1) * bytes_per_frame]
        flags.append(vad.is_speech(frame, SAMPLE_RATE))

    raw = _flags_to_segments(flags)
    merged = _merge_close(raw, max_gap_frames=merge_gap_ms // FRAME_MS)
    min_frames = min_segment_ms // FRAME_MS
    pad_samples = pad_ms * SAMPLE_RATE // 1000

    out: list[SpeechSegment] = []
    for start_f, end_f in merged:
        if (end_f - start_f) < min_frames:
            continue
        start_s = max(0, start_f * FRAME_SAMPLES - pad_samples)
        end_s = min(len(audio), end_f * FRAME_SAMPLES + pad_samples)
        out.append(SpeechSegment(start_sample=start_s, end_sample=end_s))
    logger.debug(
        "VAD: %d frames -> %d raw -> %d merged -> %d kept (>%dms)",
        n_frames, len(raw), len(merged), len(out), min_segment_ms,
    )
    return out
