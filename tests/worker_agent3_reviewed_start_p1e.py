from __future__ import annotations

import json
import os
import tempfile
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


def envelope_payload(steps: list[AgentStep]) -> str:
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
    )
    return json.dumps(
        {
            "run": template.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": True,
        },
        sort_keys=True,
    )


def recovered_case(root: str, *, name: str, current_step: int) -> None:
    plans_path = os.path.join(root, f"{name}-plans.db")
    runs_path = os.path.join(root, f"{name}-runs.db")
    reviews_path = os.path.join(root, f"{name}-reviews.db")
    first = AgentStep(
        tool="read_one",
        args={},
        risk=RiskClass.READ,
        idempotent=True,
        summary="read one",
        state=StepState.SUCCEEDED,
        result={"ok": 1},
    )
    second = AgentStep(
        tool="read_two",
        args={},
        risk=RiskClass.READ,
        idempotent=True,
        summary="read two",
    )
    steps = [first, second]

    plans = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = plans.save(envelope_payload(steps))
    run_id = f"reserved-{name}"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.close()

    run_store = AgentRunStore(runs_path)
    review_store = ReadReviewStore(reviews_path)
    review_store.configure(run_id, True)
    run = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
        state=RunState.RUNNING,
        id=run_id,
        current_step=current_step,
    )
    run_store.save_with_event(run, "run_created", {"review_reads": True})
    assert review_store.get(run_id)["waiting"] is False

    executed: list[str] = []
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
    )
    recovered_plans = PlanStore(plans_path, ttl_seconds=30)
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=recovered_plans,
        )
    )
    response = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["state"] == "running"
    assert body["run"]["current_step"] == 1
    assert body["run"]["steps"][0]["state"] == "succeeded"
    assert body["run"]["steps"][1]["state"] == "pending"
    assert executed == []

    review = review_store.get(run_id)
    assert review["enabled"] is True
    assert review["waiting"] is True
    assert review["completed_step_id"] == first.id
    assert review["completed_tool"] == "read_one"
    assert review["window_start"] == 1
    assert review["window_end"] == 2
    assert review["removable_step_ids"] == [second.id]
    assert body["read_review"]["waiting"] is True
    assert recovered_plans.reviewed_start_recovery(plan_id)[:2] == ("accepted", run_id)
    recovered_plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1e-")

# Crash window A: the READ result/state was persisted by _execute(), but
# current_step had not yet advanced to the next pending READ.
recovered_case(root, name="before-current-step-save", current_step=0)

# Crash window B: current_step was persisted, but set_waiting() had not yet
# created the human checkpoint in the separate review DB.
recovered_case(root, name="before-review-checkpoint", current_step=1)

print("30 passed, 0 failed")
