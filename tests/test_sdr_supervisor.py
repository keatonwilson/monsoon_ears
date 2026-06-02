"""ingestion/sdr_supervisor.py — leg time-sharing with a fake clock + fake procs.

No real subprocess or SDR: launch_fn returns fake processes and sleep_fn advances
a fake monotonic clock, so the whole dwell loop runs deterministically in-process.
"""

import pytest

from agents.band_manager import DwellPlan, DwellSegment
from ingestion.sdr_supervisor import SdrSupervisor, leg_command


class _Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, dt):
        self.t += max(dt, 0.0)


class FakeProc:
    """Alive until terminated/killed (unless started dead via rc)."""

    def __init__(self, rc=None):
        self._rc = rc
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = -15

    def kill(self):
        self.killed = True
        self._rc = -9

    def wait(self, timeout=None):
        return self._rc


class StubbornProc(FakeProc):
    """Ignores terminate(); only kill() stops it — forces escalation."""

    def terminate(self):
        self.terminated = True  # but stays alive (rc stays None)

    def wait(self, timeout=None):
        if not self.killed:
            raise TimeoutError("still running")
        return self._rc


def _plan(*segments, source="baseline"):
    segs = [DwellSegment(leg, sec) for leg, sec in segments]
    return DwellPlan(segments=segs, rationale="test", source=source, weights={})


def _supervisor(clock, launch_fn, plan, **kw):
    opts = dict(poll_tick_sec=2.0, cooldown_sec=1.0, term_grace_sec=5.0)
    opts.update(kw)
    return SdrSupervisor(
        plan_fn=lambda: plan,
        launch_fn=launch_fn,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
        **opts,
    )


# --- leg commands ------------------------------------------------------------


def test_leg_command_defaults_and_unknown():
    assert "ingestion.runner_analog" in leg_command("analog")
    assert "ingestion.runner_p25" in leg_command("p25")
    with pytest.raises(ValueError):
        leg_command("fm")


def test_leg_command_env_override(monkeypatch):
    monkeypatch.setenv("SDR_ANALOG_CMD", "wrapper --foo bar")
    assert leg_command("analog") == ["wrapper", "--foo", "bar"]


# --- dwell loop --------------------------------------------------------------


def test_runs_legs_in_plan_order_and_switches():
    clock = _Clock()
    launched = []

    def launch(cmd):
        p = FakeProc()
        launched.append((cmd, p))
        return p

    sup = _supervisor(clock, launch, _plan(("p25", 6), ("analog", 4)))
    sup.run(max_cycles=1)

    assert len(launched) == 2
    assert "runner_p25" in " ".join(launched[0][0])
    assert "runner_analog" in " ".join(launched[1][0])
    # Each leg was torn down before moving on (mutual exclusion).
    assert all(proc.terminated for _, proc in launched)
    # Elapsed ≈ 6 + cooldown + 4 + cooldown (fake clock advanced by sleeps).
    assert clock.t == pytest.approx(6 + 1 + 4 + 1)


def test_leg_that_exits_early_advances_without_terminate():
    clock = _Clock()
    launched = []

    def launch(cmd):
        # First leg is already dead; second is alive.
        p = FakeProc(rc=0) if not launched else FakeProc()
        launched.append((cmd, p))
        return p

    sup = _supervisor(clock, launch, _plan(("p25", 60), ("analog", 4)))
    sup.run(max_cycles=1)

    assert len(launched) == 2
    # The dead leg wasn't terminated (it was already gone) but we didn't hang
    # the full 60s on it.
    assert launched[0][1].terminated is False
    assert clock.t < 60


def test_stubborn_leg_is_killed():
    sup = _supervisor(_Clock(), lambda c: None, _plan(("p25", 1)), term_grace_sec=0.1)
    proc = StubbornProc()
    sup._stop_proc(proc)
    assert proc.terminated is True
    assert proc.killed is True


def test_request_stop_kills_active_leg_and_halts():
    sup = _supervisor(_Clock(), lambda c: None, _plan(("p25", 1)))
    proc = FakeProc()
    sup._active = proc
    sup.request_stop()
    assert sup._stop is True
    assert proc.terminated is True
    assert sup._active is None


def test_empty_plan_sleeps_without_launching():
    clock = _Clock()
    launched = []
    sup = _supervisor(
        clock, lambda c: launched.append(c) or FakeProc(),
        _plan(), empty_cycle_sec=10,
    )
    sup.run(max_cycles=1)
    assert launched == []
    assert clock.t == pytest.approx(10)


def test_watchdog_trips_after_consecutive_failures():
    """Every leg dies immediately → after max_leg_failures, the supervisor
    flags failure and stops (so main() can exit non-zero for systemd)."""
    clock = _Clock()
    launched = []

    def launch(cmd):
        p = FakeProc(rc=1)  # already dead on arrival
        launched.append((cmd, p))
        return p

    # Long dwells so a healthy leg would run for ages — only early exits advance.
    sup = _supervisor(
        clock, launch,
        _plan(("p25", 600), ("analog", 600)),
        max_leg_failures=3,
    )
    sup.run(max_cycles=5)

    assert sup.failed is True
    assert len(launched) == 3  # stopped exactly at the threshold
    assert clock.t < 600  # never waited out a dwell


def test_watchdog_streak_resets_on_healthy_leg():
    """A leg that survives its dwell clears the streak, so intermittent
    early exits (e.g. P25 broken but analog fine) never trip the watchdog."""
    clock = _Clock()
    seq = []

    def launch(cmd):
        # p25 always dies instantly; analog stays alive for its dwell.
        is_p25 = "runner_p25" in " ".join(cmd)
        p = FakeProc(rc=1) if is_p25 else FakeProc()
        seq.append(p)
        return p

    sup = _supervisor(
        clock, launch,
        _plan(("p25", 4), ("analog", 4)),
        max_leg_failures=3,
    )
    sup.run(max_cycles=5)  # 5 cycles of (fail, healthy) → streak never exceeds 1

    assert sup.failed is False


def test_status_file_written(tmp_path):
    import json

    clock = _Clock()
    status = tmp_path / "sdr_status.json"
    sup = _supervisor(
        clock, lambda c: FakeProc(), _plan(("p25", 6), ("analog", 4)),
        status_path=str(status),
    )
    sup.run(max_cycles=1)

    data = json.loads(status.read_text())
    # Last write reflects the final leg of the cycle.
    assert data["current_leg"] == "analog"
    assert data["plan_source"] == "baseline"
    assert [s["leg"] for s in data["segments"]] == ["p25", "analog"]
