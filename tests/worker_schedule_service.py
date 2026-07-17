"""Scheduler service lifecycle: dormant start, recovery and clean shutdown.

Run: PYTHONPATH=worker python3 tests/worker_schedule_service.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_runner import TickResult  # noqa: E402
from app.schedule_service import (  # noqa: E402
    DEFAULT_POLL_S,
    MAX_POLL_S,
    MIN_POLL_S,
    SchedulerService,
    poll_seconds,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


OK = TickResult(True, False, 1, 1, 0, 0, ("job",))


class FakeRunner:
    def __init__(self, *, enabled=True, actions=None):
        self.enabled = enabled
        self.actions = list(actions or [OK])
        self.calls = 0
        self.called = threading.Event()
        self._lock = threading.Lock()

    def feature_enabled(self):
        return self.enabled

    def run_once(self):
        with self._lock:
            self.calls += 1
            index = min(self.calls - 1, len(self.actions) - 1)
            action = self.actions[index]
        self.called.set()
        if isinstance(action, BaseException):
            raise action
        return action


# --- production poll parsing never becomes a busy loop ----------------------

check(poll_seconds("") == DEFAULT_POLL_S, "empty poll setting uses the conservative default")
check(poll_seconds("garbage") == DEFAULT_POLL_S, "malformed poll setting is ignored safely")
check(poll_seconds("nan") == DEFAULT_POLL_S, "non-finite poll setting is ignored safely")
check(poll_seconds("0.01") == MIN_POLL_S, "environment poll interval is clamped above busy-loop territory")
check(poll_seconds("99999") == MAX_POLL_S, "environment poll interval is bounded at one hour")
check(poll_seconds("30") == 30.0, "a normal explicit environment interval is preserved")

for bad in (0, -1, float("inf"), float("nan")):
    try:
        SchedulerService(FakeRunner(), poll_s=bad)
        check(False, f"explicit invalid poll_s {bad!r} must be refused")
    except ValueError:
        check(True, f"explicit invalid poll_s {bad!r} is refused")

# --- flag OFF: no thread, no tick, no pretend status -------------------------

off_runner = FakeRunner(enabled=False)
off = SchedulerService(off_runner, poll_s=0.01)
check(not off.start(), "start returns False while KALIV_SCHEDULER is off")
time.sleep(0.03)
check(off_runner.calls == 0, "flag OFF creates no tick side effect")
status = off.status()
check(not status.configured and not status.running and status.ticks == 0, "flag OFF status tells the truth")
check(off.stop(), "stopping a never-started service is harmless")

# --- start is immediate, idempotent and restartable --------------------------

runner = FakeRunner()
service = SchedulerService(runner, poll_s=60.0)
check(service.start(), "configured service starts")
check(runner.called.wait(0.5), "the first bounded tick runs immediately")
first_thread = service._thread
check(service.start() and service._thread is first_thread, "start is idempotent and does not create a second thread")
check(runner.calls == 1, "idempotent start does not duplicate the immediate tick")

before = time.monotonic()
check(service.stop(timeout=0.5), "stop interrupts the service cleanly")
elapsed = time.monotonic() - before
check(elapsed < 0.5, "stop interrupts Event.wait instead of waiting for the 60-second poll")
status = service.status()
check(not status.running and status.stopped_at is not None, "stopped status is persistent and observable")

runner.called.clear()
check(service.start(), "the same service may be deliberately restarted")
check(runner.called.wait(0.5) and runner.calls == 2, "restart creates exactly one new immediate tick")
check(service.stop(timeout=0.5), "restarted service also shuts down cleanly")

# --- one runner exception is visible but does not kill the service -----------

recovering_runner = FakeRunner(actions=[RuntimeError("database busy"), OK])
recovering = SchedulerService(recovering_runner, poll_s=0.1)
check(recovering.start(), "recovering service starts")
check(wait_until(lambda: recovering.status().failures == 1), "a runner exception is counted and surfaced")
first = recovering.status()
check("RuntimeError: database busy" in (first.last_error or ""), "failure status keeps the bounded real error")
check(wait_until(lambda: recovering_runner.calls >= 2), "the service survives and performs a later tick")
after = recovering.status()
check(after.running and after.ticks >= 2, "the worker thread remains alive after the exception")
check(after.failures == 1 and after.last_result == OK and after.last_error is None, "a successful recovery clears current error without erasing failure history")
check(recovering.stop(timeout=0.5), "recovering service stops cleanly")

# --- runtime flag changes are delegated to the runner, not hidden ------------

changing_runner = FakeRunner(enabled=True)
changing = SchedulerService(changing_runner, poll_s=0.02)
check(changing.start() and changing_runner.called.wait(0.5), "dynamic-flag service begins normally")
changing_runner.enabled = False
check(wait_until(lambda: changing_runner.calls >= 2), "the service continues polling after a runtime flag change")
check(not changing.status().configured, "status reflects the current feature flag, not only startup state")
check(changing.stop(timeout=0.5), "dynamic-flag service shuts down")

print(f"\n===== SCHEDULE SERVICE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
