"""One dormant scheduler tick: ScheduleStore -> JobStore -> ToolGate.

There is deliberately no loop, thread, route or model-visible tool in this
module. ``run_once`` is the execution seam a later supervisor may call after
``KALIV_SCHEDULER`` is explicitly enabled. Keeping the first integration as one
bounded tick makes every safety decision testable before anything wakes itself.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .jobs import JobStore
from .scheduler import Schedule, ScheduleClaim, ScheduleStore, fingerprint, refusal
from . import scheduler as scheduler_policy
from . import tools

_DETAIL_LIMIT = 500


@dataclass(frozen=True)
class TickResult:
    enabled: bool
    paused: bool
    claimed: int
    completed: int
    blocked: int
    failed: int
    job_ids: tuple[str, ...] = ()


class SchedulerRunner:
    """Execute one already-approved occurrence at a time through the real gate."""

    def __init__(
        self,
        schedules: ScheduleStore,
        jobs: JobStore,
        gate: tools.ToolGate,
        *,
        registry: Mapping[str, tools.Tool] | None = None,
        feature_enabled: Callable[[], bool] = scheduler_policy.enabled,
    ) -> None:
        self.schedules = schedules
        self.jobs = jobs
        self.gate = gate
        self.registry = tools.REGISTRY if registry is None else registry
        self.feature_enabled = feature_enabled

    def disable_unschedulable(self, *, now: float | None = None) -> list[str]:
        """Disable standing grants for tools that may no longer run unattended.

        A row created before schedulability existed -- an old delete_model or
        pull_model grant -- would otherwise claim, be refused by ToolGate, and
        come back every cadence forever (F-710). _permanent_refusal now stops
        the loop per occurrence, but a disabled row does not even wake, which is
        cheaper and legible: it shows as paused rather than as a job that blocks
        on a schedule. Idempotent, so running it every startup is safe.

        Returns the ids it disabled, so startup can log what it migrated.
        """
        disabled: list[str] = []
        for s in self.schedules.list_all():
            if not s.enabled:
                continue
            tool = self.registry.get(s.tool)
            # Unknown tool or one the registry now forbids on a schedule. An
            # unknown tool cannot run either, so it is disabled too rather than
            # left to fail on a loop.
            if tool is None or not getattr(tool, "schedulable", False):
                if self.schedules.set_enabled(s.schedule_id, False, now=now):
                    disabled.append(s.schedule_id)
        return disabled

    def run_once(self, *, now: float | None = None, limit: int = 20) -> TickResult:
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
        )

    def _create_job(self, claim: ScheduleClaim) -> str:
        s = claim.schedule
        detail = (
            f"schedule={s.schedule_id}; due={claim.occurrence_due_at:.3f}; "
            f"missed={claim.missed_this_claim}"
        )
        job_id = self.jobs.create(f"schedule:{s.tool}", detail=detail)
        self.jobs.update(job_id, status="running", detail=detail)
        return job_id

    def _run_claim(self, claim: ScheduleClaim, job_id: str, now: float) -> str:
        s = claim.schedule
        tool = self.registry.get(s.tool)
        if tool is None:
            self._finish_blocked(
                s,
                job_id,
                f"ukendt tool {s.tool!r}; planen er slået fra",
                risk="unknown",
                permanent=True,
                now=now,
            )
            return "blocked"

        current = fingerprint(s.tool, s.args)
        why = refusal(
            tool.risk,
            s.approved_fingerprint,
            current,
            now=now,
            expires_at=s.expires_at,
            runs_used=s.runs_used,
            max_runs=s.max_runs,
            tools_enabled=self.gate.enabled,
            tool_disabled=s.tool in self.gate.disabled_tools,
        )
        if why:
            permanent = self._permanent_refusal(s, tool, current, now)
            self._finish_blocked(
                s,
                job_id,
                why,
                risk=tool.risk,
                permanent=permanent,
                now=now,
            )
            return "blocked"

        try:
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

    def _finish_blocked(
        self,
        schedule: Schedule,
        job_id: str,
        reason: str,
        *,
        risk: str,
        permanent: bool,
        now: float,
    ) -> None:
        self.schedules.record_claim_result(schedule.schedule_id, ran=False)
        approval = (
            f"schedule:{schedule.approved_fingerprint[:12]}"
            if schedule.approved_fingerprint else None
        )
        self.gate.audit.record(
            tool=schedule.tool,
            args=schedule.args,
            risk=risk,
            outcome="blocked",
            conversation_id=f"schedule:{schedule.schedule_id}",
            confirmation_id=approval,
            origin="schedule",
            result_summary=self._bounded(reason),
        )
        if permanent:
            self.schedules.set_enabled(schedule.schedule_id, False, now=now)
            status = "failed"
        else:
            status = "cancelled"
        self.jobs.update(job_id, status=status, detail=self._bounded(reason))

    @staticmethod
    def _permanent_refusal(
        schedule: Schedule, tool: tools.Tool, current_fingerprint: str, now: float
    ) -> bool:
        if now >= schedule.expires_at:
            return True
        if schedule.max_runs and schedule.runs_used >= schedule.max_runs:
            return True
        if tool.risk == "desktop" or tool.risk not in ("read", "write"):
            return True
        # An unschedulable tool can never succeed on a schedule (F-710). ToolGate
        # refuses it every cadence, and without this the occurrence claims,
        # blocks, and comes back tomorrow forever -- a row from before
        # schedulability existed (an old delete_model grant) becomes a job that
        # fails on a loop. Refusing it permanently lets recovery stop retrying.
        if not tool.schedulable:
            return True
        if tool.risk == "write":
            return (
                not schedule.approved_fingerprint
                or schedule.approved_fingerprint != current_fingerprint
            )
        return False

    @staticmethod
    def _bounded(text: str) -> str:
        return (text or "")[:_DETAIL_LIMIT]
