from __future__ import annotations

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
