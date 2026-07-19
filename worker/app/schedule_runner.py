"""One dormant scheduler tick: ScheduleStore -> JobStore -> ToolGate.

There is deliberately no loop, thread, route or model-visible tool in this
module. ``run_once`` is the execution seam a later supervisor may call after
``KALIV_SCHEDULER`` is explicitly enabled. Keeping the first integration as one
bounded tick makes every safety decision testable before anything wakes itself.
"""
from __future__ import annotations

import logging
import time
import uuid
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
        owner_id: str | None = None,
        lease_ttl_seconds: float = 90.0,
    ) -> None:
        self.schedules = schedules
        self.jobs = jobs
        self.gate = gate
        self.registry = tools.REGISTRY if registry is None else registry
        # F-1003: this runner's identity for the owner-lease. Recovery and
        # ticking both require holding it, so a second live process can
        # neither abandon this one's in-flight claims nor double-claim.
        self.owner_id = owner_id or uuid.uuid4().hex
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.feature_enabled = feature_enabled

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
        # F-1003: recovery treats every 'reserved' occurrence as a dead
        # worker's. That is only true if no OTHER worker is alive -- so the
        # lease is a precondition. Failing to get it means a living owner
        # exists, and abandoning its in-flight claims here would refund slots
        # for runs that are happening right now.
        if not self.schedules.acquire_lease(
                self.owner_id, ttl_seconds=self.lease_ttl_seconds, now=now_v):
            logging.getLogger(__name__).warning(
                "scheduler: recovery sprunget over — en anden ejer holder "
                "lease'en (levende worker); ingen occurrences røres")
            return {"executed": [], "abandoned": [], "unknown": [],
                    "skipped_no_lease": True}
        executed_ids: list[str] = []
        abandoned_ids: list[str] = []
        unknown_ids: list[str] = []
        for occ in self.schedules.reserved_occurrences():
            conv = _occurrence_conversation(occ["schedule_id"], occ["claim_id"])
            job_id = occ.get("job_id")
            if self.gate.audit.has_execution(conv):
                prior = self.schedules.resolve_recovered(
                    occ["claim_id"], executed=True, now=now_v)
                if prior is None:
                    continue  # already resolved by a racing path
                executed_ids.append(occ["claim_id"])
                if job_id:
                    self._reconcile_job(
                        job_id, status="completed",
                        detail=("gennemført via ToolGate; worker døde før "
                                "efterregistrering — genoprettet fra audit "
                                f"(occ={occ['claim_id']})"))
                continue
            if self.gate.audit.has_attempt(conv):
                # F-1002: the worker died AFTER the attempt marker and BEFORE
                # the executed row -- the side effect MAY have happened.
                # Risk-aware: a read has no side effect worth guarding, so it
                # refunds like a clean death. Anything else keeps the slot
                # spent (refunding is how max_runs gets exceeded) and pauses
                # the grant so a human settles it before it runs again.
                sched = self.schedules.get(occ["schedule_id"])
                tool = self.registry.get(sched.tool) if sched else None
                if tool is not None and tool.risk == "read":
                    prior = self.schedules.resolve_recovered(
                        occ["claim_id"], executed=False, now=now_v)
                    if prior is None:
                        continue
                    abandoned_ids.append(occ["claim_id"])
                    if job_id:
                        self._reconcile_job(
                            job_id, status="failed",
                            detail=("worker døde under en read-kørsel; ingen "
                                    "side-effekt at beskytte — occurrence "
                                    "opgivet og budget-slot refunderet "
                                    f"(occ={occ['claim_id']})"))
                    continue
                prior = self.schedules.resolve_unknown(
                    occ["claim_id"], now=now_v)
                if prior is None:
                    continue
                unknown_ids.append(occ["claim_id"])
                if job_id:
                    self._reconcile_job(
                        job_id, status="failed",
                        detail=("udfald UKENDT: worker døde efter forsøget "
                                "blev registreret men før resultatet — "
                                "side-effekten kan være sket. Budget-slot "
                                "BEHOLDT (refusion kunne give flere kørsler "
                                "end max_runs); planen er pauset til manuel "
                                f"afklaring (occ={occ['claim_id']})"))
                if sched is not None:
                    # Pause bumps the revision like any user-intent change,
                    # so anything else in flight for the grant cancels too.
                    self.schedules.set_enabled(
                        occ["schedule_id"], False, now=now_v)
                continue
            prior = self.schedules.resolve_recovered(
                occ["claim_id"], executed=False, now=now_v)
            if prior is None:
                continue
            abandoned_ids.append(occ["claim_id"])
            if job_id:
                self._reconcile_job(
                    job_id, status="failed",
                    detail=("worker døde før kørsel; occurrence opgivet og "
                            f"budget-slot refunderet (occ={occ['claim_id']})"))
        return {"executed": executed_ids, "abandoned": abandoned_ids,
                "unknown": unknown_ids}

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

    def _hold_lease(self, now: float) -> bool:
        return self.schedules.acquire_lease(
            self.owner_id, ttl_seconds=self.lease_ttl_seconds, now=now)

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
        # F-1003: claiming requires the owner-lease. A tick without it claims
        # NOTHING -- another worker is alive and this one must not double-run
        # the same schedules. Acquire doubles as renewal for the holder.
        if not self._hold_lease(tick_at):
            logging.getLogger(__name__).warning(
                "scheduler: tick sprunget over — en anden ejer holder lease'en")
            return TickResult(True, False, 0, 0, 0, 0)

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
            claim_reserved=claim.reserved,
        )
        if why:
            permanent = self._permanent_refusal(
                s, tool, current, now, reserved=claim.reserved)
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

        # F-1002: durable ATTEMPT marker before the side effect can happen.
        # ToolGate audits 'executed' only AFTER the tool ran, so a crash in
        # that sliver used to read as "nothing happened" and refund the slot
        # -- letting a later cadence run again, and max_runs=N could produce
        # N+1 real writes. With this row, recovery can tell the three cases
        # apart: no attempt -> truly never ran (refund); attempt+executed ->
        # ran (keep); attempt alone -> UNKNOWN (keep the slot, surface it).
        # Placed after the revocation guard so cancelled claims leave no
        # attempt rows.
        self.gate.audit.record(
            tool=s.tool, args=s.args, risk=tool.risk, outcome="attempt",
            conversation_id=_occurrence_conversation(s.schedule_id, claim.claim_id),
            origin="schedule",
            result_summary="scheduler: forsøg registreret før kørsel",
        )
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
        schedule: Schedule, tool: tools.Tool, current_fingerprint: str,
        now: float, *, reserved: bool = True
    ) -> bool:
        if now >= schedule.expires_at:
            return True
        # Exhausted means the claim got NO slot -- the snapshot's runs_used
        # already counts a real claim's reservation (1.58.116), so >= here
        # refused the LAST legitimate run: max_runs=1 never ran at all, and
        # every schedule got max_runs-1 executions. runs_used > max_runs
        # stays as a corruption belt.
        if not reserved or (
                schedule.max_runs and schedule.runs_used > schedule.max_runs):
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
