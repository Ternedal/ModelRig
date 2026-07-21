#!/usr/bin/env python3
"""T-018 concurrency contract for scheduler ticks.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_single_flight.py
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.scheduler_single_flight import install_single_flight  # noqa: E402
from app.schedule_runner import SchedulerRunner  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


@dataclass(frozen=True)
class FakeTickResult:
    enabled: bool
    paused: bool
    claimed: int
    completed: int
    blocked: int
    failed: int
    job_ids: tuple[str, ...] = ()


def runner_type():
    class SlowRunner:
        def __init__(self, entered, release, *, fail_once=False):
            self.entered = entered
            self.release = release
            self.fail_once = fail_once
            self.calls = 0
            self.owner_id = "t018-test-owner"
            self.feature_enabled = lambda: True
            self.gate = SimpleNamespace(enabled=True)

        def run_once(self):
            self.calls += 1
            self.entered.set()
            self.release.wait(2.0)
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("injected slow-tool failure")
            return FakeTickResult(True, False, 1, 1, 0, 0, ("job-1",))

    install_single_flight(SlowRunner, FakeTickResult)
    return SlowRunner


check(SchedulerRunner.MAX_CONCURRENCY == 1, "production runner exposes max concurrency 1")
check(SchedulerRunner.QUEUE_CAPACITY == 0, "production runner exposes zero waiting queue")
check(hasattr(SchedulerRunner, "single_flight_status"), "production runner exposes inspectable status")

SlowRunner = runner_type()
entered = threading.Event()
release = threading.Event()
runner = SlowRunner(entered, release)
first = []
thread = threading.Thread(target=lambda: first.append(runner.run_once()))
thread.start()
check(entered.wait(1.0), "first slow tick entered")

overlap = [runner.run_once() for _ in range(12)]
status_while_busy = runner.single_flight_status()
check(runner.calls == 1, "overlap pressure never enters the underlying runner")
check(all(item.claimed == 0 for item in overlap), "every overlap is rejected before claim")
check(status_while_busy.active == 1, "status reports exactly one active tick")
check(status_while_busy.accepted == 1, "only the first tick was accepted")
check(status_while_busy.overlap_rejections == 12, "all overlap rejections are counted")
check(status_while_busy.queue_capacity == 0, "pressure creates no waiting queue")

release.set()
thread.join(2.0)
status_after = runner.single_flight_status()
check(not thread.is_alive(), "slow tick drains after release")
check(first and first[0].completed == 1, "accepted tick keeps its normal result")
check(status_after.active == 0, "single-flight slot is released after success")

FailRunner = runner_type()
entered2 = threading.Event()
release2 = threading.Event()
release2.set()
failing = FailRunner(entered2, release2, fail_once=True)
error = None
try:
    failing.run_once()
except RuntimeError as exc:
    error = exc
check(error is not None, "injected runner exception remains visible")
check(failing.single_flight_status().active == 0, "slot is released after exception")
second = failing.run_once()
check(second.completed == 1, "a later tick can enter after exception cleanup")
check(failing.calls == 2, "exception does not permanently wedge single-flight")

print(f"\n===== SCHEDULER SINGLE-FLIGHT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
