from __future__ import annotations

import json
import sqlite3
import threading
import time
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

    def resume(self, run_id: str) -> dict | None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT enabled,waiting,window_start,window_end,removable_step_ids,"
                    "completed_step_id,completed_tool FROM agent_read_reviews WHERE run_id=?",
                    (run_id,),
                ).fetchone()
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
    ) -> AgentRun:
        route = self.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._blocked_run(request, route, route.reason, proactive, allow_private_cloud)
        return self._start_reviewed(
            request,
            route,
            list(steps),
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
            review_reads=review_reads,
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
    ) -> AgentRun:
        if len(steps) > self.max_steps:
            return self._blocked_run(
                request,
                route,
                f"Plan exceeds max_steps ({self.max_steps})",
                proactive,
                allow_private_cloud,
                steps[: self.max_steps],
            )
        run = AgentRun(
            request=request,
            route=route,
            steps=steps,
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
        )
        self.store.save(run)
        self.review_store.configure(run.id, review_reads)
        self.store.event(
            run.id,
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

    def advance(self, run_id: str) -> AgentRun:
        run = self._require(run_id)
        if run.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
            return run
        if run.state == RunState.WAITING_CONFIRMATION:
            return run

        resumed = self.review_store.resume(run_id)
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
                run.current_step += 1
                self.store.save(run)
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
            if run.state == RunState.FAILED:
                return run
            completed_read = step.risk == RiskClass.READ and step.state == StepState.SUCCEEDED
            run.current_step += 1
            run.state = RunState.RUNNING
            self.store.save(run)

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

        run.state = RunState.COMPLETED
        run.answer = self.answerer(run)
        self.store.save(run)
        self.store.event(run.id, "run_completed", {"steps": len(run.steps)})
        return run
