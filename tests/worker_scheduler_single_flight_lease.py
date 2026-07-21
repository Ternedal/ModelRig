#!/usr/bin/env python3
"""T-018 composition: process-local single-flight plus durable owner lease.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_single_flight_lease.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.jobs import JobStore  # noqa: E402
from app.schedule_runner import SchedulerRunner  # noqa: E402
from app.scheduler import ScheduleStore  # noqa: E402
from app import tools as T  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


root = tempfile.mkdtemp(prefix="kaliv-single-flight-lease-")
schedules = ScheduleStore(path=os.path.join(root, "schedules.db"))
jobs = JobStore(os.path.join(root, "jobs.db"))
audit = T.AuditLog(os.path.join(root, "audit.db"))
gate = T.ToolGate(audit=audit, state_file=None)
gate.set_enabled(True)

entered = threading.Event()
release = threading.Event()
run_calls = []
original_tool = T.REGISTRY["current_datetime"]


def blocking_tool(args):
    run_calls.append(dict(args))
    entered.set()
    release.wait(3.0)
    return "slow tool completed"


T.REGISTRY["current_datetime"] = replace(original_tool, run=blocking_tool)
NOW = 2_000_000.0
try:
    schedule = schedules.create(
        "current_datetime",
        {},
        "every:60",
        max_runs=1,
        now=NOW,
    )
    runner_a = SchedulerRunner(
        schedules,
        jobs,
        gate,
        feature_enabled=lambda: True,
        owner_id="worker-a",
        lease_ttl_seconds=90.0,
    )
    runner_b = SchedulerRunner(
        schedules,
        jobs,
        gate,
        feature_enabled=lambda: True,
        owner_id="worker-b",
        lease_ttl_seconds=90.0,
    )

    first_result = []
    first_error = []

    def run_first():
        try:
            first_result.append(runner_a.run_once(now=NOW + 61))
        except Exception as exc:  # pragma: no cover - reported by assertions
            first_error.append(exc)

    thread = threading.Thread(target=run_first, name="t018-live-owner")
    thread.start()
    check(entered.wait(1.0), "worker A entered the slow ToolGate execution")

    local_overlap = runner_a.run_once(now=NOW + 61)
    check(local_overlap.claimed == 0, "same-process overlap is rejected before claim")
    check(len(run_calls) == 1, "same-process overlap never invokes the tool twice")
    check(
        runner_a.single_flight_status().overlap_rejections == 1,
        "same-process rejection is counted by the local gate",
    )

    remote_overlap = runner_b.run_once(now=NOW + 61)
    check(remote_overlap.claimed == 0, "second process is rejected by the live owner lease")
    check(len(run_calls) == 1, "cross-process overlap never invokes the tool twice")

    reserved = schedules._conn.execute(
        "SELECT COUNT(*) AS c FROM occurrences WHERE status='reserved'"
    ).fetchone()["c"]
    check(reserved == 1, "only worker A owns one reserved occurrence while live")
    check(
        schedules.get(schedule.schedule_id).runs_used == 1,
        "only one budget slot is reserved under combined pressure",
    )

    overlap_audit = [
        row
        for row in audit.recent(20)
        if row["tool"] == "scheduler_tick" and row["outcome"] == "blocked"
    ]
    check(len(overlap_audit) == 1, "local overlap has one durable explanation")
    check(
        overlap_audit[0]["conversation_id"] == "scheduler:overlap:worker-a",
        "overlap receipt identifies the rejecting owner",
    )
    check(
        "ingen budget-slot" in overlap_audit[0]["result_summary"],
        "overlap receipt explains that no extra budget was reserved",
    )

    early_recovery = runner_b.recover_interrupted(now=NOW + 70)
    check(
        early_recovery.get("skipped_no_lease") is True,
        "successor recovery cannot touch a living owner's occurrence",
    )

    release.set()
    thread.join(3.0)
    check(not thread.is_alive(), "worker A drains after the slow tool is released")
    check(not first_error, "worker A completed without an execution error")
    check(
        first_result and first_result[0].completed == 1,
        "the accepted occurrence completes exactly once",
    )

    executed = schedules._conn.execute(
        "SELECT COUNT(*) AS c FROM occurrences WHERE status='executed'"
    ).fetchone()["c"]
    check(executed == 1, "the ledger contains exactly one executed occurrence")
    check(len(run_calls) == 1, "the real tool side effect happened exactly once")

    takeover = runner_b.recover_interrupted(now=NOW + 200)
    check(
        takeover["executed"] == []
        and takeover["abandoned"] == []
        and takeover["unknown"] == [],
        "post-expiry takeover finds no orphan after a clean drain",
    )
    after_takeover = runner_b.run_once(now=NOW + 201)
    check(after_takeover.claimed == 0, "takeover cannot exceed max_runs=1")
    check(len(run_calls) == 1, "takeover does not replay the completed tool")
finally:
    release.set()
    T.REGISTRY["current_datetime"] = original_tool

print(f"\n===== SINGLE-FLIGHT + LEASE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
