"""op25 stderr filtering (C3 — keep journalctl clean)."""

import io
import logging

from ingestion.runner_p25 import _forward_op25_stderr


class _FakeProc:
    def __init__(self, data: bytes):
        self.stderr = io.BytesIO(data)


def test_op25_audio_noise_suppressed_real_lines_forwarded(caplog):
    proc = _FakeProc(
        b"failed to open audio device: default\n"
        b"locked on PCWIN NAC 0x3b1\n"
        b"\n"  # blank line ignored
    )
    log = logging.getLogger("test_op25")
    with caplog.at_level(logging.INFO, logger="test_op25"):
        _forward_op25_stderr(proc, log)

    msgs = [r.getMessage() for r in caplog.records]
    # The benign audio-device line is dropped (logged at DEBUG, below INFO)...
    assert not any("failed to open audio device" in m for m in msgs)
    # ...while genuine op25 output is forwarded.
    assert any("locked on PCWIN" in m for m in msgs)


def test_forward_handles_missing_stderr():
    class _NoStderr:
        stderr = None

    # Must not raise when op25 was launched without a captured pipe.
    _forward_op25_stderr(_NoStderr(), logging.getLogger("test_op25"))
