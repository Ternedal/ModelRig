from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
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


def materialization() -> str:
    template = AgentRun(
        request=TurnRequest(message="recover same worker", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            ),
            AgentStep(
                tool="read_two",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read two",
            ),
        ],
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


def run_case(root: str, *, exception_kind: str) -> None:
    plans = PlanStore(os.path.join(root, f"{exception_kind}-plans.db"), ttl_seconds=30)
    plan_id, _ = plans.save(materialization())
    run_store = AgentRunStore(os.path.join(root, f"{exception_kind}-runs.db"))
    review_store = ReadReviewStore(os.path.join(root, f"{exception_kind}-reviews.db"))
    executed: list[str] = []
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
    )

    original_mark = plans.mark_reviewed_start_accepted
    mark_calls = 0

    def fail_two_marks(bound_plan_id: str, run_id: str) -> None:
        nonlocal mark_calls
        mark_calls += 1
        if mark_calls <= 2:
            if exception_kind == "http":
                raise HTTPException(status_code=503, detail="transient acceptance failure")
            raise RuntimeError("transient acceptance failure")
        original_mark(bound_plan_id, run_id)

    plans.mark_reviewed_start_accepted = fail_two_marks  # type: ignore[method-assign]

    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )
    client = TestClient(app, raise_server_exceptions=False)

    first = client.post(f"/experimental/agent3/plans/{plan_id}/start")
    assert first.status_code == (503 if exception_kind == "http" else 500), first.text
    assert mark_calls == 2
    assert executed == ["read_one"]

    pending = plans.reviewed_start_recovery(plan_id)
    assert pending is not None
    assert pending[0] == "pending"
    run_id = pending[1]
    assert run_id is not None
    assert pending[2] is None

    persisted = run_store.load(run_id)
    assert persisted is not None
    assert persisted.state == RunState.RUNNING
    assert persisted.current_step == 1
    assert persisted.steps[0].state == StepState.SUCCEEDED
    assert persisted.steps[1].state == StepState.PENDING
    assert review_store.get(run_id)["enabled"] is True
    assert review_store.get(run_id)["waiting"] is True

    second = client.post(f"/experimental/agent3/plans/{plan_id}/start")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["state"] == "running"
    assert body["read_review"]["waiting"] is True
    assert executed == ["read_one"]
    assert mark_calls == 3

    accepted = plans.reviewed_start_recovery(plan_id)
    assert accepted is not None
    assert accepted[0] == "accepted"
    assert accepted[1] == run_id
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1h-")
run_case(root, exception_kind="runtime")
run_case(root, exception_kind="http")

print("28 passed, 0 failed")
