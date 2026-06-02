"""Hallucination-gate tests for ingestion.transcribe (no Whisper model needed)."""

from ingestion.transcribe import TranscriptionResult, _is_hallucination


def _result(text="Engine 31 respond to a structure fire at Speedway and Kolb",
            no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.5,
            n_segments=2) -> TranscriptionResult:
    return TranscriptionResult(
        text=text,
        no_speech_prob=no_speech_prob,
        avg_logprob=avg_logprob,
        compression_ratio=compression_ratio,
        n_segments=n_segments,
    )


def test_good_transmission_passes():
    assert _is_hallucination(_result()) is None


def test_empty_text_dropped():
    assert _is_hallucination(_result(text="")) == "empty"


def test_combined_silence_gate():
    # High no_speech AND low confidence — the original paired gate.
    reason = _is_hallucination(_result(no_speech_prob=0.8, avg_logprob=-1.1))
    assert reason and reason.startswith("no_speech_prob=")


def test_standalone_low_confidence_drop():
    # Reads as speech (low no_speech_prob) but scores poorly — the new gate.
    reason = _is_hallucination(_result(no_speech_prob=0.1, avg_logprob=-1.5))
    assert reason and reason.startswith("low_confidence")


def test_standalone_drop_threshold_is_env_configurable(monkeypatch):
    monkeypatch.setenv("LOGPROB_DROP_THRESHOLD", "-2.0")
    # -1.5 is now above the (looser) drop floor, so it survives.
    assert _is_hallucination(_result(no_speech_prob=0.1, avg_logprob=-1.5)) is None


def test_compression_ratio_gate():
    reason = _is_hallucination(_result(compression_ratio=3.0))
    assert reason and reason.startswith("compression_ratio=")


def test_invalid_env_falls_back_to_default(monkeypatch):
    # A bad override must not silently disable the gate.
    monkeypatch.setenv("LOGPROB_DROP_THRESHOLD", "not-a-float")
    assert _is_hallucination(_result(no_speech_prob=0.1, avg_logprob=-1.5)) is not None


# --- backend dispatch (_decode) — fake models, neither library installed ------

import numpy as np

from ingestion import transcribe as T


class _FasterSegment:
    """Mimics faster_whisper's Segment attributes."""
    def __init__(self, text, no_speech_prob, avg_logprob, compression_ratio):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob
        self.compression_ratio = compression_ratio


class _FakeFasterModel:
    """transcribe() returns (segment_generator, info), like faster-whisper."""
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return (s for s in self._segments), {"language": "en"}


class _FakeOpenaiModel:
    """transcribe() returns a dict with a 'segments' list, like openai-whisper."""
    def __init__(self, result):
        self._result = result
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return self._result


def test_decode_faster_backend_normalizes_segments(monkeypatch):
    monkeypatch.setenv("WHISPER_BACKEND", "faster")
    model = _FakeFasterModel([
        _FasterSegment(" Engine 31 ", 0.1, -0.3, 1.4),
        _FasterSegment("respond code 3", 0.2, -0.4, 1.6),
    ])
    text, segs = T._decode(model, np.zeros(16000, dtype=np.float32))
    assert text == "Engine 31 respond code 3"
    assert len(segs) == 2
    assert segs[0].no_speech_prob == 0.1 and segs[1].avg_logprob == -0.4
    # beam_size is passed through to the faster backend.
    assert "beam_size" in model.calls[0]


def test_decode_openai_backend_normalizes_segments(monkeypatch):
    monkeypatch.setenv("WHISPER_BACKEND", "openai")
    model = _FakeOpenaiModel({
        "text": " dispatch to Speedway ",
        "segments": [
            {"text": " dispatch", "no_speech_prob": 0.05, "avg_logprob": -0.2, "compression_ratio": 1.3},
            {"text": " to Speedway", "no_speech_prob": 0.07, "avg_logprob": -0.25, "compression_ratio": 1.5},
        ],
    })
    text, segs = T._decode(model, np.zeros(16000, dtype=np.float32))
    assert text == "dispatch to Speedway"
    assert len(segs) == 2
    assert segs[1].compression_ratio == 1.5
    assert model.calls[0].get("fp16") is False  # openai path keeps fp16=False


def test_transcribe_end_to_end_faster_applies_gates(monkeypatch):
    """transcribe() drives the faster backend and still drops low-confidence garble."""
    monkeypatch.setenv("WHISPER_BACKEND", "faster")
    garble = _FakeFasterModel([_FasterSegment("the the the", 0.1, -1.6, 1.2)])
    monkeypatch.setattr(T, "get_model", lambda: garble)
    assert T.transcribe(np.zeros(16000, dtype=np.float32)) is None  # low_confidence drop

    good = _FakeFasterModel([_FasterSegment("Med 851 to AMR for traffic", 0.1, -0.3, 1.5)])
    monkeypatch.setattr(T, "get_model", lambda: good)
    assert T.transcribe(np.zeros(16000, dtype=np.float32)) == "Med 851 to AMR for traffic"
