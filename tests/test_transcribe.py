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
