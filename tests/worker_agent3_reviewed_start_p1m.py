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


def template_run() -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="do once", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="non_idempotent_once",
                args={"value": 1},
                risk=RiskClass.READ,
                idempotent=False,
                summary="do once",
            )
        ],
    )


def payload() -> str:
    return json.dumps(
        {
            "run": template_run().to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": False,
        },
        sort_keys=True,
    )


def app_for(plans: PlanStore, runs: AgentRunStore, reviews: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        runs,
        lambda step: executed.append(step.tool) or {"side_effect": "duplicate"},
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


def stale_run_payload_cannot_replay_started_non_idempotent_step(root: str) -> None:
    plans_path = os.path.join(root, "plans.db")
    old_plans = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old_plans.save(payload())
    run_id = "rollback-run"
    old_plans.claim_reviewed_start(plan_id, run_id)
    old_owner = old_plans.start_owner
    old_plans.close()

    runs = AgentRunStore(os.path.join(root, "runs.db"))
    run = template_run()
    run.id = run_id
    runs.save_with_event(run, "run_created", {})
    stale_payload = run.to_json()

    expected = run.to_json()
    run.steps[0].state = StepState.EXECUTING
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=expected,
        kind="step_started",
        payload={"step_id": run.steps[0].id, "tool": run.steps[0].tool},
    )
    execution_payload = run.to_json()
    run.steps[0].state = StepState.SUCCEEDED
    run.steps[0].result = {"side_effect": "happened"}
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=execution_payload,
        kind="step_succeeded",
        payload={"step_id": run.steps[0].id, "tool": run.steps[0].tool},
    )

    # Simulate a partial restore/corruption of the rollbackable run payload only.
    # The independent execution-progress DB is intentionally left untouched.
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET state=?,payload=? WHERE id=?",
            (RunState.RUNNING.value, stale_payload, run_id),
        )
        runs._conn.commit()

    restored = runs.load(run_id)
    assert restored is not None
    assert restored.current_step == 0
    assert restored.steps[0].state is StepState.PENDING
    assert not runs.execution_progress_matches(restored)

    reviews = ReadReviewStore(os.path.join(root, "reviews.db"))
    reviews.configure(run_id, False)
    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery == ("pending", run_id, plans.start_owner)
    persisted = runs.load(run_id)
    assert persisted is not None and persisted.steps[0].state is StepState.PENDING
    plans.close()


def idempotent_pending_replay_remains_allowed(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "idempotent-runs.db"))
    run = template_run()
    run.id = "idempotent-run"
    run.steps[0].idempotent = True
    runs.save_with_event(run, "run_created", {})
    stale_payload = run.to_json()
    expected = run.to_json()
    run.steps[0].state = StepState.EXECUTING
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=expected,
        kind="step_started",
        payload={"step_id": run.steps[0].id},
    )
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET state=?,payload=? WHERE id=?",
            (RunState.RUNNING.value, stale_payload, run.id),
        )
        runs._conn.commit()
    restored = runs.load(run.id)
    assert restored is not None and restored.steps[0].state is StepState.PENDING
    assert runs.execution_progress_matches(restored)


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1m-")
stale_run_payload_cannot_replay_started_non_idempotent_step(root)
idempotent_pending_replay_remains_allowed(root)
print("P1m/P1n: recovery-slot/progress authority regressions passed")
