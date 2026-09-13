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


def template() -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="reserved run binding", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args={"scope": "reviewed"},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
    )


def payload(run: AgentRun) -> str:
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


def corrupt_embedded_id(runs: AgentRunStore, reserved_run_id: str, wrong_id: str) -> None:
    current = runs.load(reserved_run_id)
    assert current is not None
    current.id = wrong_id
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET payload=? WHERE id=?",
            (current.to_json(), reserved_run_id),
        )
        runs._conn.commit()
    reloaded = runs.load(reserved_run_id)
    assert reloaded is not None and reloaded.id == wrong_id


def app_for(plans: PlanStore, runs: AgentRunStore, reviews: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        runs,
        lambda step: executed.append(step.tool) or {"ok": True},
        reviews,
    )
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )
    return app


def accepted_wrong_embedded_id_fails_closed(root: str) -> None:
    plans = PlanStore(os.path.join(root, "accepted-plans.db"), ttl_seconds=30)
    reviewed = template()
    plan_id, _ = plans.save(payload(reviewed))
    reserved = "accepted-reserved-run"
    plans.claim_reviewed_start(plan_id, reserved)
    plans.mark_reviewed_start_accepted(plan_id, reserved)

    runs = AgentRunStore(os.path.join(root, "accepted-runs.db"))
    materialized = AgentRun.from_json(reviewed.to_json())
    materialized.id = reserved
    materialized.state = RunState.RUNNING
    runs.save_with_event(materialized, "run_created", {})
    corrupt_embedded_id(runs, reserved, "accepted-other-run")
    reviews = ReadReviewStore(os.path.join(root, "accepted-reviews.db"))
    reviews.configure(reserved, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    assert plans.reviewed_start_recovery(plan_id)[0] == "accepted"
    assert runs.load(reserved).id == "accepted-other-run"
    plans.close()


def pending_wrong_embedded_id_fails_closed_before_recovery_claim(root: str) -> None:
    plan_path = os.path.join(root, "pending-plans.db")
    seed = PlanStore(plan_path, ttl_seconds=30)
    reviewed = template()
    plan_id, _ = seed.save(payload(reviewed))
    reserved = "pending-reserved-run"
    seed.claim_reviewed_start(plan_id, reserved)
    old_owner = seed.reviewed_start_recovery(plan_id)[2]
    seed.close()

    # Reopening creates a fresh worker generation so this is a real recovery path.
    plans = PlanStore(plan_path, ttl_seconds=30)
    assert plans.start_owner != old_owner
    runs = AgentRunStore(os.path.join(root, "pending-runs.db"))
    materialized = AgentRun.from_json(reviewed.to_json())
    materialized.id = reserved
    materialized.state = RunState.RUNNING
    runs.save_with_event(materialized, "run_created", {})
    corrupt_embedded_id(runs, reserved, "pending-other-run")
    reviews = ReadReviewStore(os.path.join(root, "pending-reviews.db"))
    reviews.configure(reserved, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    state, run_id, owner = plans.reviewed_start_recovery(plan_id)
    assert state == "pending" and run_id == reserved
    # Fail before taking recovery authority for the mismatched payload.
    assert owner == old_owner
    assert runs.load(reserved).id == "pending-other-run"
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1n-")
accepted_wrong_embedded_id_fails_closed(root)
pending_wrong_embedded_id_fails_closed_before_recovery_claim(root)
print("P1n: URL-scoped desktop publication + reserved run-id binding regressions passed")
