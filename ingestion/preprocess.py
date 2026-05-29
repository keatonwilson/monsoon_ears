import numpy as np
from scipy.signal import butter, filtfilt


def preprocess_radio_audio(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Bandpass voice band (300–3400 Hz) and normalize to peak ±1.0."""
    if audio.size == 0:
        return audio
    nyq = sr / 2
    low, high = 300 / nyq, 3400 / nyq
    b, a = butter(4, [low, high], btype="band")
    filtered = filtfilt(b, a, audio)
    peak = np.max(np.abs(filtered))
    if peak == 0:
        return filtered.astype(np.float32)
    return (filtered / peak).astype(np.float32)
