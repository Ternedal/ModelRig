"""T-018 explicit scheduler single-flight, backpressure and drain semantics."""
from __future__ import annotations

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import tools as T  # noqa: E402
from app.jobs import JobStore  # noqa: E402
from app.schedule_runner import (  # noqa: E402
    EXECUTION_MODEL,
    MAX_CONCURRENCY,
    SchedulerRunner,
)
from app.scheduler import ScheduleStore  # noqa: E402

NOW = 2_000_000.0
passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_runner(tool_name, run):
    root = tempfile.mkdtemp(prefix="scheduler-single-flight-")
    schedules = ScheduleStore(os.path.join(root, "schedules.db"))
    jobs = JobStore(os.path.join(root, "jobs.db"))
    audit = T.AuditLog(os.path.join(root, "audit.db"))
    gate = T.ToolGate(audit=audit, state_file=None)
    gate.set_enabled(True)
    T.REGISTRY[tool_name] = T.Tool(
        name=tool_name,
        description="single-flight fixture",
        risk="read",
        schedulable=True,
        run=run,
    )
    return schedules, jobs, gate, SchedulerRunner(
        schedules, jobs, gate, feature_enabled=lambda: True
    )


for invalid in (0, 2, -1, True):
    try:
        root = tempfile.mkdtemp(prefix="scheduler-concurrency-config-")
        schedules = ScheduleStore(os.path.join(root, "schedules.db"))
        jobs = JobStore(os.path.join(root, "jobs.db"))
        audit = T.AuditLog(os.path.join(root, "audit.db"))
        gate = T.ToolGate(audit=audit, state_file=None)
        SchedulerRunner(schedules, jobs, gate, max_concurrency=invalid)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        try:
            schedules.close()
        except Exception:
            pass
    check(rejected, f"unsupported max_concurrency={invalid!r} is rejected")

started = threading.Event()
release = threading.Event()
executions = []
tool_name = "_single_flight_slow"


def slow_tool(args):
    started.set()
    release.wait(2.0)
    executions.append(dict(args))
    return "done"


schedules, jobs, gate, runner = make_runner(tool_name, slow_tool)
try:
    first = schedules.create(tool_name, {"n": 1}, "every:60", now=NOW)
    second = schedules.create(tool_name, {"n": 2}, "every:60", now=NOW + 1)
    keep_claiming = threading.Event()
    keep_claiming.set()
    result_box = {}

    thread = threading.Thread(
        target=lambda: result_box.setdefault(
            "first",
            runner.run_once(
                now=NOW + 62,
                limit=2,
                should_continue=keep_claiming.is_set,
            ),
        )
    )
    thread.start()
    check(started.wait(1.0), "the first claimed occurrence begins execution")
    reserved = schedules.reserved_occurrences()
    check(len(reserved) == 1, "only one durable occurrence is reserved while the tool is slow")
    check(
        len(schedules.due(now=NOW + 62)) == 1,
        "the remaining due backlog stays in SQLite rather than an in-memory batch",
    )

    competing = runner.run_once(now=NOW + 62, limit=1)
    check(competing.busy and competing.claimed == 0, "a competing tick gets bounded busy backpressure")
    check(competing.execution_model == EXECUTION_MODEL, "busy result names the execution model")
    check(competing.max_concurrency == MAX_CONCURRENCY, "busy result publishes the concurrency bound")
    check(len(schedules.reserved_occurrences()) == 1, "the competing tick reserves no extra occurrence")

    keep_claiming.clear()
    release.set()
    thread.join(2.0)
    check(not thread.is_alive(), "the active tool drains to a terminal result")
    first_result = result_box["first"]
    check(first_result.claimed == 1 and first_result.completed == 1,
          "shutdown callback prevents a second claim after the active action")
    check(executions == [{"n": 1}], "only the oldest due occurrence executed in the first flight")
    check(len(schedules.due(now=NOW + 62)) == 1, "the second occurrence remains durably due")

    later = runner.run_once(now=NOW + 62, limit=1)
    check(later.claimed == 1 and later.completed == 1, "a later flight drains the durable backlog")
    check(executions == [{"n": 1}, {"n": 2}], "the backlog preserves due-order without parallel execution")
    check(schedules.get(first.schedule_id).runs_used == 1, "first schedule budget is charged once")
    check(schedules.get(second.schedule_id).runs_used == 1, "second schedule budget is charged once")
finally:
    release.set()
    T.REGISTRY.pop(tool_name, None)
    schedules.close()

# The lane is released even when claim storage raises before returning work.
tool_name = "_single_flight_storage_failure"
schedules, jobs, gate, runner = make_runner(tool_name, lambda args: "unused")
try:
    original_claim_due = schedules.claim_due
    calls = {"count": 0}

    def flaky_claim_due(*, now=None, limit=20):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("synthetic claim failure")
        return original_claim_due(now=now, limit=limit)

    schedules.claim_due = flaky_claim_due
    try:
        runner.run_once(now=NOW + 61)
        raised = False
    except RuntimeError:
        raised = True
    check(raised, "claim storage failure remains visible to the service")
    retry = runner.run_once(now=NOW + 61)
    check(not retry.busy, "an exception releases the single-flight lane")
finally:
    T.REGISTRY.pop(tool_name, None)
    schedules.close()

print(f"\n===== SCHEDULER SINGLE FLIGHT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
