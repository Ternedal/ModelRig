"""One dormant scheduler tick: ScheduleStore -> JobStore -> ToolGate.

There is deliberately no loop, thread, route or model-visible tool in this
module. ``run_once`` is the execution seam a later supervisor may call after
``KALIV_SCHEDULER`` is explicitly enabled. Keeping the first integration as one
bounded tick makes every safety decision testable before anything wakes itself.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .jobs import JobStore


def _occurrence_conversation(schedule_id: str, claim_id: str) -> str:
    """The audit conversation id for one scheduled occurrence (T-012).

    Carries the claim_id so crash recovery can ask the audit 'did THIS
    occurrence execute?' with one equality match. Keeps the 'schedule:' prefix
    every existing consumer filters on.
    """
    return f"schedule:{schedule_id}:occ:{claim_id}"
from .scheduler import Schedule, ScheduleClaim, ScheduleStore, fingerprint, refusal
from . import scheduler as scheduler_policy
from . import tools

_DETAIL_LIMIT = 500
EXECUTION_MODEL = "single_flight"
MAX_CONCURRENCY = 1


@dataclass(frozen=True)
class TickResult:
    enabled: bool
    paused: bool
    claimed: int
    completed: int
    blocked: int
    failed: int
    job_ids: tuple[str, ...] = ()
    busy: bool = False
    execution_model: str = EXECUTION_MODEL
    max_concurrency: int = MAX_CONCURRENCY


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
        self._flight = threading.Lock()

    def recover_interrupted(self, *, now: float | None = None) -> dict:
        """Resolve occurrences whose worker died mid-flight, with evidence (T-012).

        A 'reserved' occurrence at startup means the worker took the slot and
        never recorded an outcome. That covers three different crashes, and they
        must not be treated the same:

          * died before the job was created            -> nothing ran
          * died after the job, before ToolGate ran    -> nothing ran
          * died AFTER ToolGate ran the side effect,
            before the result was recorded             -> it RAN

        The audit is the earliest durable evidence of execution -- ToolGate
        writes outcome='executed' under a conversation id that carries the
        claim_id. So: evidence present -> the occurrence resolves 'executed',
        the reserved slot STAYS SPENT (refunding a run that happened is how
        max_runs gets exceeded via crash), and the job is reconciled to
        completed with a degraded-bookkeeping note. No evidence -> 'abandoned',
        the slot is refunded, and the job (if any) is closed failed-terminal so
        it does not advertise 'running' forever.

        The razor-thin residue is honest: the side effect and its audit row are
        two operations, so a crash exactly between them reads as not-executed
        and refunds a slot for a run that happened. That window is milliseconds
        wide (versus the whole claim->record span before this), cannot cause a
        re-run (the occurrence is resolved, never retried), and undercounting
        is the failure direction this scheduler prefers: duplicate or excess
        writes are worse than a miss.

        Runs before the loop can claim; idempotent -- only unresolved rows.
        """
        now_v = time.time() if now is None else now
        executed_ids: list[str] = []
        abandoned_ids: list[str] = []
        for occ in self.schedules.reserved_occurrences():
            conv = _occurrence_conversation(occ["schedule_id"], occ["claim_id"])
            ran = self.gate.audit.has_execution(conv)
            prior = self.schedules.resolve_recovered(
                occ["claim_id"], executed=ran, now=now_v)
            if prior is None:
                continue  # already resolved by a racing path
            job_id = occ.get("job_id")
            if ran:
                executed_ids.append(occ["claim_id"])
                if job_id:
                    self._reconcile_job(
                        job_id, status="completed",
                        detail=("gennemført via ToolGate; worker døde før "
                                "efterregistrering — genoprettet fra audit "
                                f"(occ={occ['claim_id']})"))
            else:
                abandoned_ids.append(occ["claim_id"])
                if job_id:
                    self._reconcile_job(
                        job_id, status="failed",
                        detail=("worker døde før kørsel; occurrence opgivet og "
                                f"budget-slot refunderet (occ={occ['claim_id']})"))
        return {"executed": executed_ids, "abandoned": abandoned_ids}

    def _reconcile_job(self, job_id: str, *, status: str, detail: str) -> None:
        """Close a dangling job best-effort; recovery must not die on JobStore."""
        try:
            self.jobs.update(job_id, status=status, detail=detail)
        except Exception:
            logging.getLogger(__name__).warning(
                "recovery: could not reconcile job %s to %s", job_id, status)

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

    def run_once(
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
        )

    def _create_job(self, claim: ScheduleClaim) -> str:
        s = claim.schedule
        detail = (
            f"schedule={s.schedule_id}; due={claim.occurrence_due_at:.3f}; "
            f"missed={claim.missed_this_claim}; occ={claim.claim_id}"
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
                claim_id=claim.claim_id,
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
                claim_id=claim.claim_id,
            )
            return "blocked"

        # T-013: the claim is a snapshot, and the batch executes sequentially --
        # minutes can pass between the claim and this point. Re-read the LIVE
        # grant immediately before ToolGate: deleted, paused, or a different
        # revision/approval than the claim was taken under means the user
        # changed the grant after the claim, and the stale occurrence must not
        # run. Deliberately NOT permanent -- the user's change was intentional;
        # the schedule continues under its new terms at its next due time, and
        # the reserved budget slot is refunded by the release path.
        guard = self.schedules.current_guard(s.schedule_id)
        if (guard is None
                or not guard["enabled"]
                or guard["revision"] != claim.revision
                or guard["approved_fingerprint"] != s.approved_fingerprint):
            self._finish_blocked(
                s,
                job_id,
                "planen blev pauset, ændret eller slettet efter claim; "
                "occurrence annulleret og budget-slot refunderet",
                risk=tool.risk,
                permanent=False,
                now=now,
                claim_id=claim.claim_id,
            )
            return "blocked"

        try:
            result = self.gate.propose(
                s.tool,
                s.args,
                conversation_id=_occurrence_conversation(s.schedule_id, claim.claim_id),
                origin="schedule",
                pre_approved=s.approved_fingerprint,
            )
        except tools.ToolDenied as exc:
            # Kill-switch/tool state may change in the milliseconds after the
            # policy check. The gate is authoritative; leave the schedule alive
            # so a later cadence may run after Anders re-enables it.
            self.schedules.record_claim_result(s.schedule_id, ran=False, claim_id=claim.claim_id)
            self.jobs.update(
                job_id,
                status="cancelled",
                detail=self._bounded(f"ToolGate afviste kørslen: {exc}"),
            )
            return "blocked"
        except tools.ToolError as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False, claim_id=claim.claim_id)
            self.jobs.update(
                job_id,
                status="failed",
                detail=self._bounded(f"tool-fejl: {exc}"),
            )
            return "failed"
        except Exception as exc:
            self.schedules.record_claim_result(s.schedule_id, ran=False, claim_id=claim.claim_id)
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
                claim_id=claim.claim_id,
            )
            return "blocked"

        duration = int(result.get("duration_ms") or 0)
        return self._finish_executed(s, job_id, duration, now, claim.claim_id)

    def _finish_executed(
        self,
        schedule: Schedule,
        job_id: str,
        duration_ms: int,
        now: float,
        claim_id: str,
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
                claim_id=claim_id,
            )
            if recorded is None:
                raise RuntimeError("schedule disappeared after execution")
        except Exception as exc:
            disabled = False
            try:
                disabled = self.schedules.set_enabled(
                    schedule.schedule_id,
                    False,
                    now=now,
                ) is True
            except Exception:
                # The schedule store is already failing. The claimed occurrence
                # was consumed before execution, and a later tick will meet the
                # same store boundary rather than retrying inside this call.
                pass

            recovery = (
                "planen er slået fra for at undgå en ekstra kørsel"
                if disabled
                else "planen kunne ikke slås fra; kontrollér den før næste kørsel"
            )
            warning = self._bounded(
                f"{detail}; efterregistrering fejlede ({type(exc).__name__}); "
                f"{recovery}"
            )
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

    def _finish_blocked(
        self,
        schedule: Schedule,
        job_id: str,
        reason: str,
        *,
        risk: str,
        permanent: bool,
        now: float,
        claim_id: str,
    ) -> None:
        # A blocked occurrence did not run: release its reserved budget slot.
        self.schedules.record_claim_result(
            schedule.schedule_id, ran=False, claim_id=claim_id)
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
