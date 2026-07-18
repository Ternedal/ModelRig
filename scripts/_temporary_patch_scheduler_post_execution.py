from pathlib import Path

runner_path = Path("worker/app/schedule_runner.py")
text = runner_path.read_text(encoding="utf-8")
old = '''        try:
            result = self.gate.propose(
                s.tool,
                s.args,
                conversation_id=f"schedule:{s.schedule_id}",
                origin="schedule",
                pre_approved=s.approved_fingerprint,
            )
            # A scheduled action must never park for a card. Reaching this state
            # means the gate contract changed underneath the scheduler.
            if result.get("status") == "confirmation_required":
                self._finish_blocked(
                    s,
                    job_id,
                    "scheduled action unexpectedly requested confirmation; plan disabled",
                    risk=tool.risk,
                    permanent=True,
                    now=now,
                )
                return "blocked"

            self.schedules.record_claim_result(s.schedule_id, ran=True)
            duration = int(result.get("duration_ms") or 0)
            self.jobs.update(
                job_id,
                status="completed",
                detail=f"{s.tool} gennemført via ToolGate ({duration} ms)",
            )
            return "completed"
        except tools.ToolDenied as exc:
            # Kill-switch/tool state may change in the milliseconds after the
            # policy check. The gate is authoritative; leave the schedule alive
            # so a later cadence may run after Anders re-enables it.
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="cancelled",
                detail=self._bounded(f"ToolGate afviste kørslen: {exc}"),
            )
            return "blocked"
        except tools.ToolError as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="failed",
                detail=self._bounded(f"tool-fejl: {exc}"),
            )
            return "failed"
        except Exception as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="failed",
                detail=self._bounded(f"uventet scheduler-fejl: {type(exc).__name__}: {exc}"),
            )
            return "failed"
'''
new = '''        try:
            result = self.gate.propose(
                s.tool,
                s.args,
                conversation_id=f"schedule:{s.schedule_id}",
                origin="schedule",
                pre_approved=s.approved_fingerprint,
            )
        except tools.ToolDenied as exc:
            # Kill-switch/tool state may change in the milliseconds after the
            # policy check. The gate is authoritative; leave the schedule alive
            # so a later cadence may run after Anders re-enables it.
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="cancelled",
                detail=self._bounded(f"ToolGate afviste kørslen: {exc}"),
            )
            return "blocked"
        except tools.ToolError as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="failed",
                detail=self._bounded(f"tool-fejl: {exc}"),
            )
            return "failed"
        except Exception as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False)
            self.jobs.update(
                job_id,
                status="failed",
                detail=self._bounded(f"uventet scheduler-fejl: {type(exc).__name__}: {exc}"),
            )
            return "failed"

        # A returned result means ToolGate has already executed and audited the
        # action. Everything below is bookkeeping. A database failure here must
        # never reinterpret a completed write as a tool failure that looks safe
        # to retry.
        if result.get("status") == "confirmation_required":
            # A scheduled action must never park for a card. Reaching this state
            # means the gate contract changed underneath the scheduler.
            self._finish_blocked(
                s,
                job_id,
                "scheduled action unexpectedly requested confirmation; plan disabled",
                risk=tool.risk,
                permanent=True,
                now=now,
            )
            return "blocked"

        duration = int(result.get("duration_ms") or 0)
        return self._finish_executed(s, job_id, duration, now)

    def _finish_executed(
        self,
        schedule: Schedule,
        job_id: str,
        duration_ms: int,
        now: float,
    ) -> str:
        """Record post-execution truth without turning success into a retry.

        ToolGate has already run the side effect before this method starts. The
        schedule and job live in separate SQLite databases, so their updates
        cannot be one transaction. If schedule accounting fails, disable the
        standing grant when possible and still report the tool execution as
        completed. If only JobStore fails, the run budget is already durable;
        the audit remains the authoritative execution receipt.
        """
        detail = f"{schedule.tool} gennemført via ToolGate ({duration_ms} ms)"
        try:
            recorded = self.schedules.record_claim_result(
                schedule.schedule_id,
                ran=True,
            )
            if recorded is None:
                raise RuntimeError("schedule disappeared after execution")
        except Exception as exc:
            warning = self._bounded(
                f"{detail}; efterregistrering fejlede ({type(exc).__name__}); "
                "planen er slået fra for at undgå en ekstra kørsel"
            )
            try:
                self.schedules.set_enabled(schedule.schedule_id, False, now=now)
            except Exception:
                # The schedule store is already failing. The claimed occurrence
                # was consumed before execution, and a later tick will meet the
                # same store boundary rather than retrying inside this call.
                pass
            try:
                self.jobs.update(job_id, status="completed", detail=warning)
            except Exception:
                # Do not let a second bookkeeping store rewrite execution truth.
                pass
            return "completed"

        try:
            self.jobs.update(job_id, status="completed", detail=detail)
        except Exception:
            # The schedule budget is durable and ToolGate already audited the
            # execution. A JobStore outage must not turn that into "failed".
            pass
        return "completed"
'''
if text.count(old) != 1:
    raise SystemExit(f"expected scheduler block exactly once, found {text.count(old)}")
runner_path.write_text(text.replace(old, new), encoding="utf-8")


test_path = Path("tests/worker_schedule_post_execution.py")
test_path.write_text('''"""A completed scheduled side effect cannot become a retry on bookkeeping failure.

Run: PYTHONPATH=worker python3 tests/worker_schedule_post_execution.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import tools as T  # noqa: E402
from app.schedule_runner import SchedulerRunner  # noqa: E402
from app.scheduler import Schedule, ScheduleClaim, fingerprint  # noqa: E402


passed = failed = 0
NOW = 1_000_000.0


def check(condition: bool, name: str) -> None:
    global passed, failed
    print(f"  {'PASS' if condition else 'FAIL'}: {name}")
    passed += bool(condition)
    failed += not condition


class FakeGate:
    enabled = True
    disabled_tools: set[str] = set()

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def propose(self, tool: str, args: dict, **_kwargs) -> dict:
        self.calls.append((tool, dict(args)))
        return {"status": "executed", "duration_ms": 17}


class FailingScheduleAccounting:
    def __init__(self, schedule: Schedule, *, fail_record: bool) -> None:
        self.schedule = schedule
        self.fail_record = fail_record
        self.recorded: list[bool] = []
        self.disabled: list[tuple[str, bool, float]] = []

    def record_claim_result(self, schedule_id: str, *, ran: bool):
        assert schedule_id == self.schedule.schedule_id
        self.recorded.append(ran)
        if self.fail_record:
            raise OSError("schedule database unavailable")
        return self.schedule

    def set_enabled(self, schedule_id: str, enabled: bool, *, now: float):
        self.disabled.append((schedule_id, enabled, now))
        return True


class RecordingJobs:
    def __init__(self, *, fail_completed: bool = False) -> None:
        self.fail_completed = fail_completed
        self.updates: list[dict] = []

    def update(self, job_id: str, **fields) -> None:
        assert job_id == "job-1"
        self.updates.append(dict(fields))
        if self.fail_completed and fields.get("status") == "completed":
            raise OSError("job database unavailable")


def make_case(*, fail_record: bool, fail_completed: bool = False):
    name = "_post_execution_write"
    args = {"text": "already written"}
    schedule = Schedule(
        schedule_id="schedule-1",
        tool=name,
        args=args,
        cadence="every:60",
        approved_fingerprint=fingerprint(name, args),
        expires_at=9e18,
        max_runs=1,
        runs_used=0,
        due_at=NOW,
        missed=0,
        enabled=True,
    )
    tool = T.Tool(
        name=name,
        description="post-execution test write",
        risk="write",
        sensitivity="private",
        schedulable=True,
        run=lambda _args: "unused by fake gate",
    )
    schedules = FailingScheduleAccounting(schedule, fail_record=fail_record)
    jobs = RecordingJobs(fail_completed=fail_completed)
    gate = FakeGate()
    runner = SchedulerRunner(
        schedules,
        jobs,
        gate,
        registry={name: tool},
        feature_enabled=lambda: True,
    )
    claim = ScheduleClaim(schedule, occurrence_due_at=NOW, missed_this_claim=0)
    return runner, claim, schedules, jobs, gate


# The dangerous path: ToolGate returned success, then schedule accounting failed.
# The old broad except called record_claim_result(..., ran=False) and returned
# "failed", making an already-executed write look retryable.
runner, claim, schedules, jobs, gate = make_case(fail_record=True)
outcome = runner._run_claim(claim, "job-1", NOW)
check(outcome == "completed", "post-execution schedule failure preserves completed truth")
check(gate.calls == [(claim.schedule.tool, claim.schedule.args)], "the tool is invoked exactly once")
check(schedules.recorded == [True], "success is never rewritten as ran=False")
check(
    schedules.disabled == [(claim.schedule.schedule_id, False, NOW)],
    "the standing grant is disabled after failed run-budget accounting",
)
check(
    jobs.updates and jobs.updates[-1].get("status") == "completed",
    "the job remains completed rather than advertising a safe retry",
)
check(
    "efterregistrering fejlede" in jobs.updates[-1].get("detail", ""),
    "the persisted job explains the degraded bookkeeping without exception text",
)
check(
    "schedule database unavailable" not in jobs.updates[-1].get("detail", ""),
    "internal database error text is not exposed",
)


# If the schedule budget is durable but JobStore is down, execution truth is
# still completed and the schedule must not be disabled or recorded as failed.
runner, claim, schedules, jobs, gate = make_case(
    fail_record=False,
    fail_completed=True,
)
outcome = runner._run_claim(claim, "job-1", NOW)
check(outcome == "completed", "JobStore failure cannot reinterpret an executed action")
check(schedules.recorded == [True], "run budget is recorded exactly once")
check(schedules.disabled == [], "a healthy schedule store is not disabled")
check(gate.calls == [(claim.schedule.tool, claim.schedule.args)], "JobStore failure causes no tool retry")


print(f"\\n===== SCHEDULE POST-EXECUTION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
''', encoding="utf-8")
