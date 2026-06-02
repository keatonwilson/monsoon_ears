"""SDR supervisor — the single owner of the one RTL-SDR.

Only one RF decoder can hold the dongle at a time, so the analog scanner
(`ingestion.runner_analog`) and op25/P25 (`ingestion.runner_p25`) must not run
simultaneously. Previously they were independent systemd services that would
fight for the device; this supervisor replaces that by being the *only* thing
that launches an RF leg. It runs exactly one leg at a time, holds it for the
dwell window the Band Manager assigns, then cleanly tears it down (SIGTERM +
a short cooldown so the device is fully released) and switches.

Mutual exclusion is therefore structural: at most one child process — the
supervisor's current leg — ever has the SDR open. Each leg's runner already
terminates its own children (runner_p25 stops op25) and releases the dongle on
SIGTERM, so a leg switch is just "kill the child, wait, start the next."

Run with:
    uv run python -m ingestion.sdr_supervisor

The whole loop is dependency-injected (launch_fn, time_fn, sleep_fn, plan_fn) so
it runs in tests with fake processes and a fake clock — no real subprocess or
dongle required.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from dotenv import load_dotenv

from agents.band_manager import LEG_ANALOG, LEG_P25, DwellPlan, DwellSegment, plan_dwell

logger = logging.getLogger(__name__)


# --- leg commands ------------------------------------------------------------

# Each leg is a single child process whose runner owns its own decoder and
# releases the SDR on SIGTERM. Overridable via env for the Pi (e.g. to wrap in a
# specific interpreter); defaults invoke the module with the current interpreter.
def leg_command(leg: str) -> list[str]:
    if leg == LEG_ANALOG:
        override = os.getenv("SDR_ANALOG_CMD", "").strip()
        return override.split() if override else [sys.executable, "-m", "ingestion.runner_analog"]
    if leg == LEG_P25:
        override = os.getenv("SDR_P25_CMD", "").strip()
        return override.split() if override else [sys.executable, "-m", "ingestion.runner_p25"]
    raise ValueError(f"unknown leg: {leg!r}")


# --- process abstraction -----------------------------------------------------


class LegProcess(Protocol):
    """The slice of subprocess.Popen the supervisor relies on (fakeable)."""

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None): ...


def _default_launch(cmd: list[str]) -> LegProcess:
    logger.info("launching leg: %s", " ".join(cmd))
    return subprocess.Popen(cmd)


# --- supervisor --------------------------------------------------------------


class SdrSupervisor:
    def __init__(
        self,
        plan_fn: Callable[[], DwellPlan] = plan_dwell,
        launch_fn: Callable[[list[str]], LegProcess] = _default_launch,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        status_path: str | None = None,
        poll_tick_sec: float = 2.0,
        cooldown_sec: float = 3.0,
        term_grace_sec: float = 10.0,
        empty_cycle_sec: float = 60.0,
        max_leg_failures: int = 5,
    ):
        self.plan_fn = plan_fn
        self.launch_fn = launch_fn
        self._time = time_fn
        self._sleep = sleep_fn
        self.status_path = status_path
        self.poll_tick_sec = poll_tick_sec
        self.cooldown_sec = cooldown_sec
        self.term_grace_sec = term_grace_sec
        self.empty_cycle_sec = empty_cycle_sec
        # Watchdog: a healthy leg runs to its dwell deadline (we terminate it);
        # a leg that exits on its own beforehand has crashed/failed to start. If
        # we can't get ANY leg to survive its dwell `max_leg_failures` times in a
        # row, the SDR (or its config) is wedged — exit non-zero so systemd's
        # Restart=on-failure recovers us. A persistent failure then trips the
        # unit's StartLimit and lands it in a visible `failed` state, instead of
        # the silent "active but hung" zombie we hit when op25 fast-failed every
        # cycle and eventually wedged the dongle.
        self.max_leg_failures = max_leg_failures

        self._stop = False
        self._active: LegProcess | None = None
        self._active_leg: str | None = None
        self._fail_streak = 0
        self._failed = False

    @property
    def failed(self) -> bool:
        """True if the watchdog tripped (caller should exit non-zero)."""
        return self._failed

    # -- control --
    def request_stop(self) -> None:
        """Idempotent: stop the loop and kill whatever leg is live."""
        if self._stop:
            return
        self._stop = True
        logger.info("supervisor: stop requested")
        self._release_active()

    # -- main loop --
    def run(self, max_cycles: int | None = None) -> None:
        """Run dwell cycles until stopped (or max_cycles, for tests)."""
        cycles = 0
        try:
            while not self._stop and (max_cycles is None or cycles < max_cycles):
                plan = self.plan_fn()
                logger.info(
                    "supervisor: cycle plan source=%s rationale=%s segments=%s",
                    plan.source, plan.rationale,
                    [(s.leg, round(s.seconds)) for s in plan.segments],
                )
                if not plan.segments:
                    # No leg to run: free the dongle so a stale plan can't pin it.
                    self._release_active()
                    self._write_status(plan, current=None, ends_in=self.empty_cycle_sec)
                    self._interruptible_sleep(self.empty_cycle_sec)
                    cycles += 1
                    continue
                for seg in plan.segments:
                    if self._stop:
                        break
                    self._run_segment(seg, plan)
                cycles += 1
        finally:
            # Whatever we leave running must release the SDR on the way out.
            self._release_active()

    def _run_segment(self, seg: DwellSegment, plan: DwellPlan) -> None:
        # Reuse the live leg if it's already the one this segment wants and still
        # running — switching legs costs a full decoder restart (op25 re-locks the
        # P25 control channel, ~20s of missed calls). Holding the same leg across a
        # segment/cycle boundary avoids that entirely (e.g. a P25-only posture
        # never re-locks).
        reused = (
            self._active is not None
            and self._active_leg == seg.leg
            and self._active.poll() is None
        )
        if not reused:
            self._acquire_leg(seg.leg)
        proc = self._active
        self._write_status(plan, current=seg, ends_in=seg.seconds)
        logger.info("supervisor: leg %s for %.0fs (%s)", seg.leg, seg.seconds,
                    "continued" if reused else "fresh")

        deadline = self._time() + seg.seconds
        exited_early = False
        while not self._stop and self._time() < deadline:
            rc = proc.poll()
            if rc is not None:
                logger.warning("supervisor: leg %s exited early (rc=%s)", seg.leg, rc)
                exited_early = True
                break
            remaining = deadline - self._time()
            self._sleep(min(self.poll_tick_sec, max(0.0, remaining)))

        if exited_early:
            # The decoder died; drop the handle so the next segment relaunches it
            # (with a cooldown) instead of trying to reuse a dead process.
            self._active = None
            self._active_leg = None
        self._note_leg_outcome(seg, exited_early)

    def _acquire_leg(self, leg: str) -> None:
        """Tear down any currently-held leg and launch ``leg`` fresh. The cooldown
        between teardown and launch lets the SDR fully release (avoids
        "usb_claim_interface error / device busy" on a fast switch); it's skipped
        on the first launch when nothing is held."""
        if self._active is not None:
            self._stop_proc(self._active)
            self._active = None
            self._active_leg = None
            if not self._stop and self.cooldown_sec > 0:
                self._interruptible_sleep(self.cooldown_sec)
        cmd = leg_command(leg)
        self._active = self.launch_fn(cmd)
        self._active_leg = leg

    def _release_active(self) -> None:
        """Stop the live leg (if any) without a trailing cooldown — used on
        shutdown and empty cycles, where nothing follows."""
        if self._active is not None:
            self._stop_proc(self._active)
            self._active = None
            self._active_leg = None

    def _note_leg_outcome(self, seg: DwellSegment, exited_early: bool) -> None:
        """Track consecutive leg failures; trip the watchdog if we can't keep
        any leg alive. Reaching the dwell deadline (the common case) is healthy
        and clears the streak."""
        if self._stop:
            return  # a requested stop isn't a failure
        if not exited_early:
            if self._fail_streak:
                logger.info("supervisor: leg %s healthy; clearing failure streak (was %d)",
                            seg.leg, self._fail_streak)
            self._fail_streak = 0
            return
        self._fail_streak += 1
        logger.warning("supervisor: leg %s failed (%d/%d consecutive)",
                       seg.leg, self._fail_streak, self.max_leg_failures)
        if self._fail_streak >= self.max_leg_failures:
            logger.error(
                "supervisor: %d consecutive leg failures — exiting non-zero so the "
                "service restarts and re-initializes a wedged SDR", self._fail_streak,
            )
            self._failed = True
            self._stop = True

    def _stop_proc(self, proc: LegProcess) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=self.term_grace_sec)
        except Exception:  # noqa: BLE001 — TimeoutExpired (or fake) → escalate
            logger.warning("supervisor: leg did not exit in %.0fs, killing", self.term_grace_sec)
            proc.kill()
            try:
                proc.wait(timeout=self.term_grace_sec)
            except Exception:  # noqa: BLE001
                logger.error("supervisor: leg failed to die after kill")

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = self._time() + seconds
        while not self._stop and self._time() < deadline:
            self._sleep(min(self.poll_tick_sec, max(0.0, deadline - self._time())))

    # -- observability --
    def _write_status(self, plan: DwellPlan, current: DwellSegment | None, ends_in: float) -> None:
        if not self.status_path:
            return
        now = datetime.now(timezone.utc)
        status = {
            "generated_at": now.isoformat(),
            "current_leg": current.leg if current else None,
            "current_dwell_sec": current.seconds if current else None,
            "ends_at": (now + timedelta(seconds=ends_in)).isoformat(),
            "plan_source": plan.source,
            "rationale": plan.rationale,
            "weights": plan.weights,
            "segments": [{"leg": s.leg, "seconds": round(s.seconds, 1)} for s in plan.segments],
        }
        try:
            with open(self.status_path, "w") as fh:
                json.dump(status, fh, indent=2)
        except OSError as exc:
            logger.warning("supervisor: could not write status file: %s", exc)


# --- entrypoint --------------------------------------------------------------


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    load_dotenv()
    _setup_logging()
    log = logging.getLogger("sdr_supervisor")

    sup = SdrSupervisor(
        status_path=os.getenv("SDR_STATUS_FILE", "").strip() or None,
        poll_tick_sec=float(os.getenv("SDR_POLL_TICK_SEC", 2.0)),
        cooldown_sec=float(os.getenv("SDR_LEG_COOLDOWN_SEC", 3.0)),
        term_grace_sec=float(os.getenv("SDR_TERM_GRACE_SEC", 10.0)),
        max_leg_failures=int(os.getenv("SDR_MAX_LEG_FAILURES", 5)),
    )

    signal.signal(signal.SIGINT, lambda *_: sup.request_stop())
    signal.signal(signal.SIGTERM, lambda *_: sup.request_stop())

    log.info("SDR supervisor starting")
    try:
        sup.run()
    finally:
        sup.request_stop()
    if sup.failed:
        log.error("SDR supervisor exiting non-zero after repeated leg failures")
        return 1
    log.info("SDR supervisor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
