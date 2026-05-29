import numpy as np

from ingestion.preprocess import preprocess_radio_audio


def test_empty_input_returns_empty():
    out = preprocess_radio_audio(np.array([], dtype=np.float32))
    assert out.size == 0


def test_normalizes_to_unit_peak():
    sr = 16000
    t = np.arange(sr) / sr
    # 1 kHz tone (in passband) scaled to 0.2 peak
    audio = 0.2 * np.sin(2 * np.pi * 1000 * t)
    out = preprocess_radio_audio(audio.astype(np.float32), sr=sr)
    assert out.dtype == np.float32
    assert np.isclose(np.max(np.abs(out)), 1.0, atol=1e-3)


def test_bandpass_attenuates_low_freq():
    sr = 16000
    t = np.arange(sr) / sr
    # 60 Hz tone — well below the 300 Hz HPF cutoff.
    audio = np.sin(2 * np.pi * 60 * t).astype(np.float32)
    out = preprocess_radio_audio(audio, sr=sr)
    # After bandpass, energy of the original 60 Hz tone should drop massively.
    in_rms = float(np.sqrt(np.mean(audio ** 2)))
    out_rms = float(np.sqrt(np.mean(out ** 2)))
    assert out_rms < in_rms * 0.5


def test_bandpass_passes_voice_freq():
    sr = 16000
    t = np.arange(sr) / sr
    # 1 kHz tone — squarely in the voice passband.
    audio = 0.5 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    out = preprocess_radio_audio(audio, sr=sr)
    out_rms = float(np.sqrt(np.mean(out ** 2)))
    # After normalization the in-band tone should land near sqrt(0.5).
    assert out_rms > 0.5
