#!/usr/bin/env python3
"""T-018 lifecycle fault tests for explicit scheduler single-flight.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_single_flight_service.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_service import SchedulerService  # noqa: E402
from app.scheduler_single_flight import install_single_flight  # noqa: E402

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


class BlockingRunner:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.owner_id = "t018-service-owner"
        self.gate = type("Gate", (), {"enabled": True})()
        self.feature_enabled = lambda: True

    def disable_unschedulable(self):
        return []

    def recover_interrupted(self):
        return {"executed": [], "abandoned": [], "unknown": []}

    def run_once(self):
        self.calls += 1
        self.entered.set()
        self.release.wait(3.0)
        return FakeTickResult(True, False, 1, 1, 0, 0, (f"job-{self.calls}",))


install_single_flight(BlockingRunner, FakeTickResult)
runner = BlockingRunner()
service = SchedulerService(runner, poll_s=60.0)

check(service.start(), "service starts with explicit single-flight runner")
check(runner.entered.wait(1.0), "service tick enters blocking tool path")

overlap_started = time.monotonic()
overlap = runner.run_once()
overlap_elapsed = time.monotonic() - overlap_started
check(overlap.claimed == 0, "manual overlap is rejected before claim")
check(overlap_elapsed < 0.25, "zero-queue overlap returns immediately")
check(runner.calls == 1, "overlap never enters underlying execution")

check(not service.stop(timeout=0.05), "shutdown timeout reports active tick honestly")
check(service.status().running, "service remains running after failed drain")
check(runner.single_flight_status().active == 1, "single-flight remains active during timeout")

runner.release.set()
check(service.stop(timeout=2.0), "shutdown succeeds after active tick drains")
check(not service.status().running, "service reports stopped after drain")
status = runner.single_flight_status()
check(status.active == 0, "single-flight slot is empty after shutdown")
check(status.overlap_rejections == 1, "shutdown scenario preserves overlap audit counter")

runner.entered.clear()
check(service.start(), "drained service can start again")
check(runner.entered.wait(1.0), "restarted service executes a new tick")
check(service.stop(timeout=2.0), "restarted service stops cleanly")
check(runner.calls >= 2, "restart creates a later accepted execution")

print(f"\n===== SCHEDULER SINGLE-FLIGHT SERVICE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
