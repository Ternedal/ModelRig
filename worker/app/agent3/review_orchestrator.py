from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Iterable

from .core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RouteKind,
    RunConflict,
    RunState,
    StepState,
    TurnRequest,
)


class ReadReviewError(RuntimeError):
    pass


class ReadReviewStore:
    """Persistent, external policy state for opt-in read review checkpoints.

    Review state deliberately lives outside AgentRun JSON. Existing serialized
    runs therefore stay backward-compatible and the ordinary orchestrator keeps
    its exact behavior. A row is created only for explicitly reviewed runs.
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_read_reviews ("
            "run_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, waiting INTEGER NOT NULL, "
            "window_start INTEGER, window_end INTEGER, removable_step_ids TEXT NOT NULL, "
            "completed_step_id TEXT, completed_tool TEXT, updated_at REAL NOT NULL)"
        )
        self._conn.commit()

    def configure(self, run_id: str, enabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_read_reviews("
                "run_id,enabled,waiting,window_start,window_end,removable_step_ids,"
                "completed_step_id,completed_tool,updated_at) VALUES(?,?,0,NULL,NULL,'[]',NULL,NULL,?) "
                "ON CONFLICT(run_id) DO UPDATE SET enabled=excluded.enabled,waiting=0,"
                "window_start=NULL,window_end=NULL,removable_step_ids='[]',"
                "completed_step_id=NULL,completed_tool=NULL,updated_at=excluded.updated_at",
                (run_id, 1 if enabled else 0, time.time()),
            )
            self._conn.commit()

    def set_waiting(
        self,
        run_id: str,
        *,
        completed_step_id: str,
        completed_tool: str,
        window_start: int,
        window_end: int,
        removable_step_ids: list[str],
    ) -> None:
        with self._lock:
            changed = self._conn.execute(
                "UPDATE agent_read_reviews SET waiting=1,window_start=?,window_end=?,"
                "removable_step_ids=?,completed_step_id=?,completed_tool=?,updated_at=? "
                "WHERE run_id=? AND enabled=1",
                (
                    window_start,
                    window_end,
                    json.dumps(removable_step_ids, ensure_ascii=False),
                    completed_step_id,
                    completed_tool,
                    time.time(),
                    run_id,
                ),
            ).rowcount
            self._conn.commit()
        if changed != 1:
            raise ReadReviewError("read review is not enabled for this run")

    def resume(
        self,
        run_id: str,
        *,
        expected_completed_step_id: str | None = None,
    ) -> dict | None:
        """Consume one waiting checkpoint, optionally bound to its exact step.

        The expected step check deliberately lives inside the same IMMEDIATE
        transaction as clearing `waiting`. A stale or concurrent Resume for an
        older checkpoint therefore cannot validate checkpoint A and later clear
        checkpoint B after another request has already advanced the run.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT enabled,waiting,window_start,window_end,removable_step_ids,"
                    "completed_step_id,completed_tool FROM agent_read_reviews WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if expected_completed_step_id is not None:
                    if row is None or row[0] != 1 or row[1] != 1:
                        raise ReadReviewError("read review checkpoint is no longer waiting")
                    if row[5] != expected_completed_step_id:
                        raise ReadReviewError("read review checkpoint authority is stale")
                if row is None or row[0] != 1 or row[1] != 1:
                    self._conn.commit()
                    return None
                self._conn.execute(
                    "UPDATE agent_read_reviews SET waiting=0,window_start=NULL,window_end=NULL,"
                    "removable_step_ids='[]',completed_step_id=NULL,completed_tool=NULL,updated_at=? "
                    "WHERE run_id=?",
                    (time.time(), run_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "window_start": row[2],
            "window_end": row[3],
            "removable_step_ids": json.loads(row[4]),
            "completed_step_id": row[5],
            "completed_tool": row[6],
        }

    def get(self, run_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT enabled,waiting,window_start,window_end,removable_step_ids,"
                "completed_step_id,completed_tool,updated_at "
                "FROM agent_read_reviews WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            return {
                "enabled": False,
                "waiting": False,
                "window_start": None,
                "window_end": None,
                "removable_step_ids": [],
                "completed_step_id": None,
                "completed_tool": None,
                "updated_at": None,
            }
        return {
            "enabled": bool(row[0]),
            "waiting": bool(row[1]),
            "window_start": row[2],
            "window_end": row[3],
            "removable_step_ids": json.loads(row[4]),
            "completed_step_id": row[5],
            "completed_tool": row[6],
            "updated_at": row[7],
        }


class ReviewingAgent3Orchestrator(Agent3Orchestrator):
    """Agent3Orchestrator with an opt-in checkpoint after successful reads.

    Default runs are behavior-identical to Agent3Orchestrator. Reviewed runs
    pause only when a successful read is followed by one or more contiguous
    pending reads. An explicit advance resumes execution; applying a replan does
    not resume the run automatically.
    """

    def __init__(
        self,
        store: AgentRunStore,
        executor,
        review_store: ReadReviewStore,
        **kwargs,
    ):
        super().__init__(store, executor, **kwargs)
        self.review_store = review_store
        # Same-run execution must be single-flight inside one worker. A fixed
        # stripe set avoids an unbounded lock registry while still ensuring
        # recovery and ordinary Resume for the same run share one RLock.
        # Cancel deliberately does NOT take this lock: it must remain able to
        # win through the store CAS while an external tool is still running.
        self._run_execution_locks = tuple(threading.RLock() for _ in range(64))

    def run_execution_guard(self, run_id: str):
        return self._run_execution_locks[hash(run_id) % len(self._run_execution_locks)]

    def start(
        self,
        request: TurnRequest,
        caps: CapabilitySnapshot,
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
        review_reads: bool = False,
    ) -> AgentRun:
        if self.planner is None:
            from .core import RunConflict

            raise RunConflict("no planner configured; use start_with_steps for the experimental draft")
        route = self.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._blocked_run(request, route, route.reason, proactive, allow_private_cloud)
        steps = self.planner(request, route.kind)
        return self._start_reviewed(
            request,
            route,
            steps,
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
            review_reads=review_reads,
        )

    def start_with_steps(
        self,
        request: TurnRequest,
        caps: CapabilitySnapshot,
        steps: Iterable[AgentStep],
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
        review_reads: bool = False,
        run_id: str | None = None,
    ) -> AgentRun:
        route = self.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._blocked_run(
                request, route, route.reason, proactive, allow_private_cloud, run_id=run_id
            )
        return self._start_reviewed(
            request,
            route,
            list(steps),
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
            review_reads=review_reads,
            run_id=run_id,
        )

    def _start_reviewed(
        self,
        request: TurnRequest,
        route,
        steps: list[AgentStep],
        *,
        proactive: bool,
        allow_private_cloud: bool,
        review_reads: bool,
        run_id: str | None = None,
    ) -> AgentRun:
        if len(steps) > self.max_steps:
            return self._blocked_run(
                request,
                route,
                f"Plan exceeds max_steps ({self.max_steps})",
                proactive,
                allow_private_cloud,
                steps[: self.max_steps],
                run_id=run_id,
            )
        run = AgentRun(
            request=request,
            route=route,
            steps=steps,
            id=run_id or str(uuid.uuid4()),
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
        )
        # Two databases cannot share a transaction, so ordering carries the
        # safety (F-814). The dangerous outcome is a run that EXISTS with no
        # review row, because get() defaults a missing row to enabled=False: a
        # run that was supposed to wait for human review would silently proceed
        # unreviewed after a crash. So the review policy is made durable FIRST.
        #
        # If we crash after configure() but before the run is saved, the result
        # is an orphan review row for a run that does not exist -- harmless, get()
        # is never called for a run with no record. The reverse -- a run with no
        # policy -- is the one that fails open, so it is the one we exclude by
        # construction. Then run + its creation event land atomically in the run
        # DB via save_with_event (F-712), so the run never exists without the
        # event that explains it either.
        self.review_store.configure(run.id, review_reads)
        self.store.save_with_event(
            run,
            "run_created",
            {
                "route": route.kind.value,
                "steps": len(steps),
                "review_reads": review_reads,
            },
        )
        return self.advance(run.id)

    @staticmethod
    def _pending_read_window(run: AgentRun) -> tuple[int, int] | None:
        start = run.current_step
        end = start
        while end < len(run.steps):
            item = run.steps[end]
            if item.state != StepState.PENDING or item.risk != RiskClass.READ:
                break
            end += 1
        return (start, end) if end > start else None

    def recover_read_review_checkpoint_if_due(self, run_id: str) -> AgentRun | None:
        """Rebuild a reviewed-read checkpoint lost in a cross-store crash gap.

        The run DB and read-review DB cannot share a transaction. A crash can
        therefore persist a successful READ (and possibly its advanced
        ``current_step``) before ``set_waiting`` reaches the review DB. Reviewed
        Start recovery must restore that human authority before it considers
        calling ``advance``; otherwise the next pending reads would execute
        without the explicit Resume the review policy requires.

        Returning ``None`` means no checkpoint is due. Returning the run means
        recovery must stop at the existing or reconstructed checkpoint.
        """
        run = self._require(run_id)
        review = self.review_store.get(run.id)
        if not review["enabled"]:
            return None
        if review["waiting"]:
            return run

        completed: AgentStep | None = None

        # Crash window A: _execute() persisted the successful read, but the
        # orchestrator had not yet advanced current_step and saved the run.
        if run.current_step < len(run.steps):
            current = run.steps[run.current_step]
            if current.state == StepState.SUCCEEDED and current.risk == RiskClass.READ:
                completed = current
                conflict = self._advance_succeeded_step(run)
                if conflict is not None:
                    return conflict

        # Crash window B: current_step was already saved, but set_waiting() had
        # not yet made the human checkpoint durable in the review DB.
        if completed is None and run.current_step > 0:
            previous = run.steps[run.current_step - 1]
            if previous.state == StepState.SUCCEEDED and previous.risk == RiskClass.READ:
                completed = previous

        if completed is None:
            return None

        window = self._pending_read_window(run)
        if window is None:
            return None

        start, end = window
        removable_ids = [item.id for item in run.steps[start:end]]
        self.review_store.set_waiting(
            run.id,
            completed_step_id=completed.id,
            completed_tool=completed.tool,
            window_start=start,
            window_end=end,
            removable_step_ids=removable_ids,
        )
        self.store.event(
            run.id,
            "replan_review_required",
            {
                "completed_step_id": completed.id,
                "completed_tool": completed.tool,
                "window_start": start,
                "window_end": end,
                "removable_step_ids": removable_ids,
                "recovered": True,
            },
        )
        return run

    def advance(
        self,
        run_id: str,
        *,
        expected_review_step_id: str | None = None,
    ) -> AgentRun:
        with self.run_execution_guard(run_id):
            return self._advance_locked(
                run_id, expected_review_step_id=expected_review_step_id
            )

    def _advance_locked(
        self,
        run_id: str,
        *,
        expected_review_step_id: str | None = None,
    ) -> AgentRun:
        run = self._require(run_id)
        if expected_review_step_id is not None and run.state in {
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.WAITING_CONFIRMATION,
        }:
            raise ReadReviewError("read review checkpoint is no longer resumable")
        if run.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
            return run
        if run.state == RunState.WAITING_CONFIRMATION:
            return run

        resumed = self.review_store.resume(
            run_id,
            expected_completed_step_id=expected_review_step_id,
        )
        if resumed is not None:
            self.store.event(
                run.id,
                "replan_review_resumed",
                {
                    "current_step": run.current_step,
                    "previous_window_start": resumed["window_start"],
                    "previous_window_end": resumed["window_end"],
                },
            )

        while run.current_step < len(run.steps):
            step = run.steps[run.current_step]

            if step.state == StepState.SUCCEEDED:
                conflict = self._advance_succeeded_step(run)
                if conflict is not None:
                    return conflict
                continue
            if step.state == StepState.EXECUTING:
                step.state = StepState.BLOCKED
                step.error = "Execution was interrupted; verify the side effect manually before resuming"
                run.state = RunState.BLOCKED
                run.error = step.error
                self.store.save(run)
                self.store.event(
                    run.id,
                    "interrupted_execution",
                    {"step_id": step.id, "tool": step.tool},
                )
                return run
            if step.state == StepState.WAITING_CONFIRMATION:
                run.state = RunState.WAITING_CONFIRMATION
                self.store.save(run)
                return run
            if step.state in {StepState.DENIED, StepState.BLOCKED, StepState.FAILED}:
                run.state = RunState.BLOCKED if step.state == StepState.BLOCKED else RunState.FAILED
                run.error = step.error or f"Step {step.state.value}"
                self.store.save(run)
                return run

            decision = self.policy.evaluate(
                step,
                proactive=run.proactive,
                allow_private_cloud=run.allow_private_cloud,
            )
            self.store.event(
                run.id,
                "policy_decision",
                {
                    "step_id": step.id,
                    "tool": step.tool,
                    "action": decision.action,
                    "reason": decision.reason,
                },
            )
            if decision.action == "block":
                step.state = StepState.BLOCKED
                step.error = decision.reason
                run.state = RunState.BLOCKED
                run.error = decision.reason
                self.store.save(run)
                return run
            if decision.action == "confirm" and step.state != StepState.APPROVED:
                step.state = StepState.WAITING_CONFIRMATION
                step.confirmation_digest = self._digest(step)
                step.confirmation_expires_at = time.time() + self.confirmation_ttl_seconds
                run.state = RunState.WAITING_CONFIRMATION
                self.store.save(run)
                self.store.event(
                    run.id,
                    "confirmation_required",
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "summary": step.summary,
                        "expires_at": step.confirmation_expires_at,
                    },
                )
                return run

            self._execute(run, step)
            if run.state in {RunState.FAILED, RunState.CANCELLED, RunState.BLOCKED}:
                return run
            completed_read = step.risk == RiskClass.READ and step.state == StepState.SUCCEEDED
            conflict = self._advance_succeeded_step(run)
            if conflict is not None:
                return conflict

            review = self.review_store.get(run.id)
            if completed_read and review["enabled"]:
                window = self._pending_read_window(run)
                if window is not None:
                    start, end = window
                    removable_ids = [item.id for item in run.steps[start:end]]
                    self.review_store.set_waiting(
                        run.id,
                        completed_step_id=step.id,
                        completed_tool=step.tool,
                        window_start=start,
                        window_end=end,
                        removable_step_ids=removable_ids,
                    )
                    self.store.event(
                        run.id,
                        "replan_review_required",
                        {
                            "completed_step_id": step.id,
                            "completed_tool": step.tool,
                            "window_start": start,
                            "window_end": end,
                            "removable_step_ids": removable_ids,
                        },
                    )
                    return run

        expected_payload = run.to_json()
        answer = self.answerer(run)
        run.state = RunState.COMPLETED
        run.answer = answer
        if not self.store.save_with_event_if_unchanged(
            run,
            expected_state=RunState.RUNNING,
            expected_payload=expected_payload,
            kind="run_completed",
            payload={"steps": len(run.steps)},
        ):
            fresh = self._require(run.id)
            if fresh.state == RunState.CANCELLED:
                return fresh
            raise RunConflict("run changed while final completion was being committed")
        return run