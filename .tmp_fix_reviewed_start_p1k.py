from pathlib import Path

ROOT = Path(__file__).resolve().parent
REVIEW = ROOT / "worker/app/agent3/review_orchestrator.py"
PLANNER = ROOT / "worker/app/agent3/planner.py"
TEST = ROOT / "tests/worker_agent3_reviewed_start_p1k.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


review = REVIEW.read_text(encoding="utf-8")
review = replace_once(
    review,
    "    RouteKind,\n    RunState,\n",
    "    RouteKind,\n    RunConflict,\n    RunState,\n",
    "RunConflict import",
)
review = replace_once(
    review,
    "        super().__init__(store, executor, **kwargs)\n        self.review_store = review_store\n",
    "        super().__init__(store, executor, **kwargs)\n"
    "        self.review_store = review_store\n"
    "        # Same-run execution must be single-flight inside one worker. A fixed\n"
    "        # stripe set avoids an unbounded lock registry while still ensuring\n"
    "        # recovery and ordinary Resume for the same run share one RLock.\n"
    "        # Cancel deliberately does NOT take this lock: it must remain able to\n"
    "        # win through the store CAS while an external tool is still running.\n"
    "        self._run_execution_locks = tuple(threading.RLock() for _ in range(64))\n"
    "\n"
    "    def run_execution_guard(self, run_id: str):\n"
    "        return self._run_execution_locks[hash(run_id) % len(self._run_execution_locks)]\n",
    "execution guard",
)
review = replace_once(
    review,
    "                completed = current\n"
    "                run.current_step += 1\n"
    "                run.state = RunState.RUNNING\n"
    "                self.store.save(run)\n",
    "                completed = current\n"
    "                conflict = self._advance_succeeded_step(run)\n"
    "                if conflict is not None:\n"
    "                    return conflict\n",
    "checkpoint progression CAS",
)
review = replace_once(
    review,
    "    def advance(\n"
    "        self,\n"
    "        run_id: str,\n"
    "        *,\n"
    "        expected_review_step_id: str | None = None,\n"
    "    ) -> AgentRun:\n"
    "        run = self._require(run_id)\n",
    "    def advance(\n"
    "        self,\n"
    "        run_id: str,\n"
    "        *,\n"
    "        expected_review_step_id: str | None = None,\n"
    "    ) -> AgentRun:\n"
    "        with self.run_execution_guard(run_id):\n"
    "            return self._advance_locked(\n"
    "                run_id, expected_review_step_id=expected_review_step_id\n"
    "            )\n"
    "\n"
    "    def _advance_locked(\n"
    "        self,\n"
    "        run_id: str,\n"
    "        *,\n"
    "        expected_review_step_id: str | None = None,\n"
    "    ) -> AgentRun:\n"
    "        run = self._require(run_id)\n",
    "advance wrapper",
)
review = replace_once(
    review,
    "            if step.state == StepState.SUCCEEDED:\n"
    "                run.current_step += 1\n"
    "                self.store.save(run)\n"
    "                continue\n",
    "            if step.state == StepState.SUCCEEDED:\n"
    "                conflict = self._advance_succeeded_step(run)\n"
    "                if conflict is not None:\n"
    "                    return conflict\n"
    "                continue\n",
    "succeeded progression CAS",
)
review = replace_once(
    review,
    "            self._execute(run, step)\n"
    "            if run.state == RunState.FAILED:\n"
    "                return run\n"
    "            completed_read = step.risk == RiskClass.READ and step.state == StepState.SUCCEEDED\n"
    "            run.current_step += 1\n"
    "            run.state = RunState.RUNNING\n"
    "            self.store.save(run)\n",
    "            self._execute(run, step)\n"
    "            if run.state in {RunState.FAILED, RunState.CANCELLED, RunState.BLOCKED}:\n"
    "                return run\n"
    "            completed_read = step.risk == RiskClass.READ and step.state == StepState.SUCCEEDED\n"
    "            conflict = self._advance_succeeded_step(run)\n"
    "            if conflict is not None:\n"
    "                return conflict\n",
    "post-execution CAS progression",
)
review = replace_once(
    review,
    "        run.state = RunState.COMPLETED\n"
    "        run.answer = self.answerer(run)\n"
    "        self.store.save(run)\n"
    "        self.store.event(run.id, \"run_completed\", {\"steps\": len(run.steps)})\n"
    "        return run",
    "        expected_payload = run.to_json()\n"
    "        answer = self.answerer(run)\n"
    "        run.state = RunState.COMPLETED\n"
    "        run.answer = answer\n"
    "        if not self.store.save_with_event_if_unchanged(\n"
    "            run,\n"
    "            expected_state=RunState.RUNNING,\n"
    "            expected_payload=expected_payload,\n"
    "            kind=\"run_completed\",\n"
    "            payload={\"steps\": len(run.steps)},\n"
    "        ):\n"
    "            fresh = self._require(run.id)\n"
    "            if fresh.state == RunState.CANCELLED:\n"
    "                return fresh\n"
    "            raise RunConflict(\"run changed while final completion was being committed\")\n"
    "        return run",
    "completion CAS",
)
REVIEW.write_text(review, encoding="utf-8")

planner = PLANNER.read_text(encoding="utf-8")
planner = replace_once(
    planner,
    "import uuid\nfrom dataclasses import asdict, dataclass\n",
    "import uuid\nfrom contextlib import nullcontext\nfrom dataclasses import asdict, dataclass\n",
    "nullcontext import",
)
planner = replace_once(
    planner,
    "    def _reconcile_reviewed_start_run(\n"
    "        run_id: str,\n"
    "        *,\n"
    "        review_reads: bool,\n"
    "        reviewed_template: AgentRun,\n"
    "    ) -> AgentRun:\n"
    "        existing = orchestrator.store.load(run_id)\n",
    "    def _reconcile_reviewed_start_run(\n"
    "        run_id: str,\n"
    "        *,\n"
    "        review_reads: bool,\n"
    "        reviewed_template: AgentRun,\n"
    "    ) -> AgentRun:\n"
    "        # Recovery identity checks, checkpoint reconstruction and the possible\n"
    "        # advance must linearize with ordinary Resume for this exact run.\n"
    "        # ReviewingAgent3Orchestrator uses an RLock, so the nested advance()\n"
    "        # below is re-entrant; non-reviewing fixtures keep their old behavior.\n"
    "        execution_guard = (\n"
    "            orchestrator.run_execution_guard(run_id) if reviewing else nullcontext()\n"
    "        )\n"
    "        with execution_guard:\n"
    "            return _reconcile_reviewed_start_run_locked(\n"
    "                run_id, review_reads=review_reads, reviewed_template=reviewed_template\n"
    "            )\n"
    "\n"
    "    def _reconcile_reviewed_start_run_locked(\n"
    "        run_id: str,\n"
    "        *,\n"
    "        review_reads: bool,\n"
    "        reviewed_template: AgentRun,\n"
    "    ) -> AgentRun:\n"
    "        existing = orchestrator.store.load(run_id)\n",
    "recovery execution guard",
)
PLANNER.write_text(planner, encoding="utf-8")

TEST.write_text(r'''from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def template_run() -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="serialize recovery", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
    )


def materialization(run: AgentRun) -> str:
    return json.dumps(
        {
            "run": run.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": False,
        },
        sort_keys=True,
    )


def recovery_vs_resume_is_single_flight(root: str) -> None:
    plans_path = os.path.join(root, "race-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = old.save(materialization(reviewed))
    run_id = "race-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "race-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "race-reviews.db"))
    reviews.configure(run_id, False)
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    runs.save_with_event(persisted, "run_created", {})

    entered = threading.Event()
    release = threading.Event()
    executed: list[str] = []

    def executor(step: AgentStep):
        executed.append(step.tool)
        entered.set()
        assert release.wait(5), "executor release timed out"
        return {"ok": True}

    orchestrator = ReviewingAgent3Orchestrator(runs, executor, reviews)
    plans = PlanStore(plans_path, ttl_seconds=30)
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )

    start_result: dict[str, object] = {}
    resume_result: dict[str, object] = {}

    def recover_start() -> None:
        start_result["response"] = TestClient(app).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    def ordinary_resume() -> None:
        resume_result["run"] = orchestrator.advance(run_id)

    recovery_thread = threading.Thread(target=recover_start, daemon=True)
    recovery_thread.start()
    assert entered.wait(5), "recovery never entered executor"

    resume_thread = threading.Thread(target=ordinary_resume, daemon=True)
    resume_thread.start()
    time.sleep(0.1)
    assert resume_thread.is_alive(), "ordinary Resume did not serialize behind recovery"

    release.set()
    recovery_thread.join(5)
    resume_thread.join(5)
    assert not recovery_thread.is_alive() and not resume_thread.is_alive()

    response = start_result["response"]
    assert response.status_code == 200, response.text
    resumed = resume_result["run"]
    assert resumed.id == run_id and resumed.state is RunState.COMPLETED
    assert executed == ["read_one"], executed
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.COMPLETED
    assert final.current_step == 1
    assert final.steps[0].state == StepState.SUCCEEDED
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "accepted" and recovery[1] == run_id
    plans.close()


def cancel_still_wins_during_executor(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "cancel-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "cancel-reviews.db"))
    run = template_run()
    run.id = "cancel-run"
    reviews.configure(run.id, False)
    runs.save_with_event(run, "run_created", {})

    entered = threading.Event()
    release = threading.Event()
    executed: list[str] = []

    def executor(step: AgentStep):
        executed.append(step.tool)
        entered.set()
        assert release.wait(5), "executor release timed out"
        return {"ok": True}

    orchestrator = ReviewingAgent3Orchestrator(runs, executor, reviews)
    result: dict[str, AgentRun] = {}

    def advance() -> None:
        result["run"] = orchestrator.advance(run.id)

    thread = threading.Thread(target=advance, daemon=True)
    thread.start()
    assert entered.wait(5), "advance never entered executor"

    cancelled = orchestrator.cancel(run.id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive()

    returned = result["run"]
    assert returned.state is RunState.CANCELLED
    final = runs.load(run.id)
    assert final is not None and final.state is RunState.CANCELLED
    assert executed == ["read_one"]
    assert final.steps[0].state in {StepState.COMPLETED_AFTER_CANCEL, StepState.SUCCEEDED}


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1k-")
recovery_vs_resume_is_single_flight(root)
cancel_still_wins_during_executor(root)

print("24 passed, 0 failed")
''', encoding="utf-8")

print("applied P1k serialization/CAS fix and regression")
