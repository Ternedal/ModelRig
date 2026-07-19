#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "worker/app/schedule_runner.py",
    "import logging\nimport time\n",
    "import logging\nimport threading\nimport time\n",
)
replace_once(
    "worker/app/schedule_runner.py",
    "_DETAIL_LIMIT = 500\n\n\n@dataclass(frozen=True)",
    "_DETAIL_LIMIT = 500\nEXECUTION_MODEL = \"single_flight\"\nMAX_CONCURRENCY = 1\n\n\n@dataclass(frozen=True)",
)
replace_once(
    "worker/app/schedule_runner.py",
    '''class TickResult:
    enabled: bool
    paused: bool
    claimed: int
    completed: int
    blocked: int
    failed: int
    job_ids: tuple[str, ...] = ()''',
    '''class TickResult:
    enabled: bool
    paused: bool
    claimed: int
    completed: int
    blocked: int
    failed: int
    job_ids: tuple[str, ...] = ()
    busy: bool = False
    execution_model: str = EXECUTION_MODEL
    max_concurrency: int = MAX_CONCURRENCY''',
)
replace_once(
    "worker/app/schedule_runner.py",
    '''        registry: Mapping[str, tools.Tool] | None = None,
        feature_enabled: Callable[[], bool] = scheduler_policy.enabled,
    ) -> None:
        self.schedules = schedules
        self.jobs = jobs
        self.gate = gate
        self.registry = tools.REGISTRY if registry is None else registry
        self.feature_enabled = feature_enabled''',
    '''        registry: Mapping[str, tools.Tool] | None = None,
        feature_enabled: Callable[[], bool] = scheduler_policy.enabled,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency != MAX_CONCURRENCY:
            raise ValueError(
                "schedulerens eneste understøttede execution-model er "
                "single_flight med max_concurrency=1"
            )
        self.schedules = schedules
        self.jobs = jobs
        self.gate = gate
        self.registry = tools.REGISTRY if registry is None else registry
        self.feature_enabled = feature_enabled
        self.execution_model = EXECUTION_MODEL
        self.max_concurrency = MAX_CONCURRENCY
        self._flight = threading.Lock()''',
)
replace_once(
    "worker/app/schedule_runner.py",
    '''    def run_once(self, *, now: float | None = None, limit: int = 20) -> TickResult:
        """Claim and execute a bounded batch, or do absolutely nothing when off.

        The global tool kill-switch pauses before claiming. This matters: a
        disabled system must not quietly consume tomorrow's occurrence merely
        because the scheduler woke up. A single disabled tool is checked again
        after the atomic claim; that occurrence is skipped, but the schedule is
        retained for later cadences.
        """
        tick_at = time.time() if now is None else now
        if not self.feature_enabled():
            return TickResult(False, False, 0, 0, 0, 0)
        if not self.gate.enabled:
            return TickResult(True, True, 0, 0, 0, 0)

        claims = self.schedules.claim_due(now=tick_at, limit=limit)
        completed = blocked = failed = 0
        job_ids: list[str] = []

        for claim in claims:
            job_id = self._create_job(claim)
            # Bind occurrence -> job (T-012) so recovery can reconcile a
            # dangling job to a terminal state instead of leaving it 'running'
            # forever. Separate DBs, so this cannot join the claim transaction;
            # it runs before execution, so the unbound window is cosmetic.
            self.schedules.bind_job(claim.claim_id, job_id)
            job_ids.append(job_id)
            outcome = self._run_claim(claim, job_id, tick_at)
            if outcome == "completed":
                completed += 1
            elif outcome == "blocked":
                blocked += 1
            else:
                failed += 1

        return TickResult(
            True, False, len(claims), completed, blocked, failed, tuple(job_ids)
        )''',
    '''    def run_once(
        self,
        *,
        now: float | None = None,
        limit: int = 20,
        should_continue: Callable[[], bool] | None = None,
    ) -> TickResult:
        """Run one explicit single-flight lane with no in-memory work queue.

        A competing caller gets a typed busy result and claims nothing. Inside
        the lane, occurrences are claimed one at a time; the remaining backlog
        stays durable in SQLite until the active occurrence reaches a terminal
        state. ``should_continue`` is checked before every new claim so service
        shutdown drains the current action but never reserves the next one.
        """
        tick_at = time.time() if now is None else now
        if not self.feature_enabled():
            return TickResult(False, False, 0, 0, 0, 0)
        if not self.gate.enabled:
            return TickResult(True, True, 0, 0, 0, 0)
        if not self._flight.acquire(blocking=False):
            return TickResult(True, False, 0, 0, 0, 0, busy=True)
        try:
            return self._run_single_flight(
                tick_at=tick_at,
                limit=limit,
                should_continue=should_continue or (lambda: True),
            )
        finally:
            self._flight.release()

    def _run_single_flight(
        self,
        *,
        tick_at: float,
        limit: int,
        should_continue: Callable[[], bool],
    ) -> TickResult:
        bounded_limit = max(1, min(int(limit), 100))
        completed = blocked = failed = claimed = 0
        paused = False
        job_ids: list[str] = []

        for _ in range(bounded_limit):
            if not should_continue() or not self.feature_enabled():
                break
            if not self.gate.enabled:
                paused = True
                break
            claims = self.schedules.claim_due(now=tick_at, limit=1)
            if not claims:
                break
            claim = claims[0]
            claimed += 1
            job_id = self._create_job(claim)
            # Bind occurrence -> job (T-012) so recovery can reconcile a
            # dangling job to a terminal state instead of leaving it 'running'
            # forever. Separate DBs, so this cannot join the claim transaction;
            # it runs before execution, so the unbound window is cosmetic.
            self.schedules.bind_job(claim.claim_id, job_id)
            job_ids.append(job_id)
            outcome = self._run_claim(claim, job_id, tick_at)
            if outcome == "completed":
                completed += 1
            elif outcome == "blocked":
                blocked += 1
            else:
                failed += 1

        return TickResult(
            True,
            paused,
            claimed,
            completed,
            blocked,
            failed,
            tuple(job_ids),
        )''',
)

replace_once(
    "worker/app/schedule_service.py",
    "from .schedule_runner import SchedulerRunner, TickResult",
    "from .schedule_runner import (\n    EXECUTION_MODEL,\n    MAX_CONCURRENCY,\n    SchedulerRunner,\n    TickResult,\n)",
)
replace_once(
    "worker/app/schedule_service.py",
    '''    last_result: TickResult | None
    last_error: str | None''',
    '''    last_result: TickResult | None
    last_error: str | None
    execution_model: str
    max_concurrency: int
    busy_ticks: int''',
)
replace_once(
    "worker/app/schedule_service.py",
    '''        self._last_result: TickResult | None = None
        self._last_error: str | None = None''',
    '''        self._last_result: TickResult | None = None
        self._last_error: str | None = None
        self._busy_ticks = 0''',
)
replace_once(
    "worker/app/schedule_service.py",
    '''                last_result=self._last_result,
                last_error=self._last_error,
            )''',
    '''                last_result=self._last_result,
                last_error=self._last_error,
                execution_model=getattr(
                    self.runner, "execution_model", EXECUTION_MODEL
                ),
                max_concurrency=getattr(
                    self.runner, "max_concurrency", MAX_CONCURRENCY
                ),
                busy_ticks=self._busy_ticks,
            )''',
)
replace_once(
    "worker/app/schedule_service.py",
    '''                result = self.runner.run_once()''',
    '''                result = self.runner.run_once(
                    should_continue=lambda: not self._stop.is_set()
                )''',
)
replace_once(
    "worker/app/schedule_service.py",
    '''                    self._last_result = result
                    self._last_error = None''',
    '''                    self._last_result = result
                    if result.busy:
                        self._busy_ticks += 1
                    self._last_error = None''',
)

replace_once(
    "tests/worker_schedule_service.py",
    '''        self.recovered = False''',
    '''        self.recovered = False
        self.execution_model = "single_flight"
        self.max_concurrency = 1''',
)
replace_once(
    "tests/worker_schedule_service.py",
    '''    def run_once(self):''',
    '''    def run_once(self, *, should_continue=None):
        if should_continue is not None and not should_continue():
            return TickResult(True, False, 0, 0, 0, 0)''',
)
replace_once(
    "tests/worker_schedule_service.py",
    '''check(not status.configured and not status.running and status.ticks == 0, "flag OFF status tells the truth")''',
    '''check(not status.configured and not status.running and status.ticks == 0, "flag OFF status tells the truth")
check(status.execution_model == "single_flight" and status.max_concurrency == 1,
      "service status publishes the explicit bounded execution model")
check(status.busy_ticks == 0, "service status starts with no rejected competing ticks")''',
)

Path("tests/worker_scheduler_single_flight.py").write_text(
    '''"""T-018 explicit scheduler single-flight, backpressure and drain semantics."""
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
    second = schedules.create(tool_name, {"n": 2}, "every:60", now=NOW)
    keep_claiming = threading.Event()
    keep_claiming.set()
    result_box = {}

    thread = threading.Thread(
        target=lambda: result_box.setdefault(
            "first",
            runner.run_once(
                now=NOW + 61,
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
        len(schedules.due(now=NOW + 61)) == 1,
        "the remaining due backlog stays in SQLite rather than an in-memory batch",
    )

    competing = runner.run_once(now=NOW + 61, limit=1)
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
    check(len(schedules.due(now=NOW + 61)) == 1, "the second occurrence remains durably due")

    later = runner.run_once(now=NOW + 61, limit=1)
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

print(f"\\n===== SCHEDULER SINGLE FLIGHT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
''',
    encoding="utf-8",
)

Path("SCHEDULER_EXECUTION_MODEL.md").write_text(
    '''# Scheduler execution model — T-018 explicit single-flight

**Status: draft implementation and tests only. Not merged into the frozen physical-validation candidate.**

ModelRig deliberately starts with one scheduler execution lane:

- `execution_model=single_flight`;
- `max_concurrency=1` and every other value is rejected;
- a competing tick receives `busy=true` and claims nothing;
- no in-memory queue exists;
- each occurrence is claimed from SQLite only after the previous one is terminal;
- the durable `due_at` order is the queue and provides natural backpressure;
- shutdown lets the active ToolGate call finish, then blocks the next claim;
- a claim/storage exception releases the lane for a later tick;
- status exposes the model, bound and count of busy ticks.

This is safer than a worker pool for the first Scheduler pilot. It preserves the
existing occurrence ledger, approval, revocation and recovery truth without
introducing cross-thread cancellation or result-ordering ambiguity. A future pool
would require a separate reviewed design and migration; increasing an environment
number cannot enable it.

## Acceptance evidence in the draft

`tests/worker_scheduler_single_flight.py` proves:

1. unsupported concurrency values are rejected;
2. a slow tool leaves only one reserved occurrence;
3. the remaining backlog stays due in SQLite;
4. a concurrent tick returns busy and reserves nothing;
5. a stop callback drains the active tool but takes no next claim;
6. a later flight processes the backlog in due order;
7. each schedule consumes one budget slot;
8. a claim exception releases the lane.

`tests/worker_schedule_service.py` additionally proves that service status
publishes the explicit model and bound. Physical pilot evidence is still required
before Scheduler promotion.
''',
    encoding="utf-8",
)
