from pathlib import Path

planner = Path("worker/app/agent3/planner.py")
text = planner.read_text(encoding="utf-8")
old = '''                    if existing.state is RunState.RUNNING:\n                        _assert_reviewed_run_identity(existing, reviewed_template)\n                    if existing.state is RunState.CANCELLED and reviewing:\n'''
new = '''                    # Accepted replay is observation-only, but any state that\n                    # can still resume execution must remain bound to the exact\n                    # immutable reviewed plan before later Resume/Confirm may run.\n                    if existing.state in {RunState.RUNNING, RunState.WAITING_CONFIRMATION}:\n                        _assert_reviewed_run_identity(existing, reviewed_template)\n                    if existing.state is RunState.CANCELLED and reviewing:\n'''
if old not in text:
    raise SystemExit("missing accepted replay identity anchor")
text = text.replace(old, new, 1)
planner.write_text(text, encoding="utf-8")

regression = Path("tests/worker_agent3_reviewed_start_p1m.py")
if regression.exists():
    raise SystemExit("P1m regression already exists")
regression.write_text(r'''from __future__ import annotations

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


def reviewed_template(*, later_args: dict | None = None) -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="accepted confirmation identity", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="write_one",
                args={"value": "reviewed"},
                risk=RiskClass.WRITE,
                idempotent=False,
                summary="write one",
            ),
            AgentStep(
                tool="read_after",
                args=later_args or {"scope": "reviewed"},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read after",
            ),
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


def accepted_waiting_run(run_id: str, *, later_args: dict | None = None) -> AgentRun:
    run = reviewed_template(later_args=later_args)
    run.id = run_id
    run.state = RunState.WAITING_CONFIRMATION
    run.current_step = 0
    run.steps[0].state = StepState.WAITING_CONFIRMATION
    run.steps[1].state = StepState.PENDING
    return run


def app_for(
    plans: PlanStore,
    runs: AgentRunStore,
    reviews: ReadReviewStore,
    executed: list[str],
) -> FastAPI:
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


def accepted_waiting_confirmation_tamper_fails_closed(root: str) -> None:
    plans = PlanStore(os.path.join(root, "tampered-plans.db"), ttl_seconds=30)
    reviewed = reviewed_template()
    plan_id, _ = plans.save(payload(reviewed))
    run_id = "accepted-waiting-tampered"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.mark_reviewed_start_accepted(plan_id, run_id)

    runs = AgentRunStore(os.path.join(root, "tampered-runs.db"))
    tampered = accepted_waiting_run(run_id, later_args={"scope": "tampered"})
    runs.save_with_event(
        tampered,
        "confirmation_required",
        {"step_id": tampered.steps[0].id},
    )
    reviews = ReadReviewStore(os.path.join(root, "tampered-reviews.db"))
    reviews.configure(run_id, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    persisted = runs.load(run_id)
    assert persisted is not None
    assert persisted.state is RunState.WAITING_CONFIRMATION
    assert persisted.steps[0].state is StepState.WAITING_CONFIRMATION
    assert persisted.steps[1].args == {"scope": "tampered"}
    assert plans.reviewed_start_recovery(plan_id)[0] == "accepted"
    plans.close()


def accepted_waiting_confirmation_exact_replays_observation_only(root: str) -> None:
    plans = PlanStore(os.path.join(root, "exact-plans.db"), ttl_seconds=30)
    reviewed = reviewed_template()
    plan_id, _ = plans.save(payload(reviewed))
    run_id = "accepted-waiting-exact"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.mark_reviewed_start_accepted(plan_id, run_id)

    runs = AgentRunStore(os.path.join(root, "exact-runs.db"))
    exact = accepted_waiting_run(run_id)
    # Preserve immutable step ids from the reviewed template as a real materialized
    # run would. Step ids are excluded from the digest, but this keeps the fixture
    # representative of the confirmation surface.
    exact.steps[0].id = reviewed.steps[0].id
    exact.steps[1].id = reviewed.steps[1].id
    runs.save_with_event(
        exact,
        "confirmation_required",
        {"step_id": exact.steps[0].id},
    )
    reviews = ReadReviewStore(os.path.join(root, "exact-reviews.db"))
    reviews.configure(run_id, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["state"] == "waiting_confirmation"
    assert executed == []
    persisted = runs.load(run_id)
    assert persisted is not None and persisted.state is RunState.WAITING_CONFIRMATION
    assert persisted.steps[1].state is StepState.PENDING
    assert plans.reviewed_start_recovery(plan_id)[0] == "accepted"
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1m-")
accepted_waiting_confirmation_tamper_fails_closed(root)
accepted_waiting_confirmation_exact_replays_observation_only(root)
print("P1m: accepted WAITING_CONFIRMATION identity binding passed")
''', encoding="utf-8")

print("applied accepted WAITING_CONFIRMATION identity fix and regression")
