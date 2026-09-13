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


def payload(first: AgentStep, second: AgentStep) -> str:
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[first, second],
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


def fail_closed_case(root: str, *, mode: str) -> None:
    plans_path = os.path.join(root, f"{mode}-plans.db")
    runs_path = os.path.join(root, f"{mode}-runs.db")
    reviews_path = os.path.join(root, f"{mode}-reviews.db")

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

    plans = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = plans.save(payload(first, second))
    run_id = f"reserved-{mode}"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.close()

    run_store = AgentRunStore(runs_path)
    run = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[first, second],
        state=RunState.RUNNING,
        id=run_id,
        current_step=1,
    )
    run_store.save_with_event(run, "run_created", {"review_reads": True})

    review_store = ReadReviewStore(reviews_path)
    if mode == "disabled":
        review_store.configure(run_id, False)
    else:
        assert review_store.get(run_id)["enabled"] is False

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
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []

    persisted = run_store.load(run_id)
    assert persisted is not None
    assert persisted.state == RunState.RUNNING
    assert persisted.current_step == 1
    assert persisted.steps[0].state == StepState.SUCCEEDED
    assert persisted.steps[1].state == StepState.PENDING

    recovery = recovered_plans.reviewed_start_recovery(plan_id)
    assert recovery is not None
    assert recovery[0] == "pending"
    assert recovery[1] == run_id
    recovered_plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1f-")
fail_closed_case(root, mode="missing")
fail_closed_case(root, mode="disabled")

print("24 passed, 0 failed")
