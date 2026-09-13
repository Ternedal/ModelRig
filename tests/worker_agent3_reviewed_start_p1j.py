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


def template_run(*, proactive: bool = False, allow_private_cloud: bool = False, two_reads: bool = False) -> AgentRun:
    steps = [
        AgentStep(
            tool="read_one",
            args={},
            risk=RiskClass.READ,
            idempotent=True,
            summary="read one",
        )
    ]
    if two_reads:
        steps.append(
            AgentStep(
                tool="read_two",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read two",
            )
        )
    return AgentRun(
        request=TurnRequest(message="recover authority", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
        proactive=proactive,
        allow_private_cloud=allow_private_cloud,
    )


def payload(run: AgentRun, *, review_reads: bool) -> str:
    return json.dumps(
        {
            "run": run.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": review_reads,
        },
        sort_keys=True,
    )


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


def prepare_pending(root: str, name: str, reviewed: AgentRun) -> tuple[str, str, str, AgentRunStore, ReadReviewStore]:
    plans_path = os.path.join(root, f"{name}-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(reviewed, review_reads=False))
    run_id = f"{name}-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()
    runs = AgentRunStore(os.path.join(root, f"{name}-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, f"{name}-reviews.db"))
    return plans_path, plan_id, run_id, runs, reviews


def execution_policy_flag_tamper_is_pending(root: str) -> None:
    cases = (
        ("private", True, False, "allow_private_cloud"),
        ("proactive", False, True, "proactive"),
    )
    for name, tampered_value, reviewed_value, field in cases:
        reviewed = template_run(
            proactive=True if field == "proactive" else False,
            allow_private_cloud=False,
        )
        if field == "proactive":
            reviewed.proactive = reviewed_value
        plans_path, plan_id, run_id, runs, reviews = prepare_pending(root, name, reviewed)
        persisted = AgentRun.from_json(reviewed.to_json())
        persisted.id = run_id
        setattr(persisted, field, tampered_value)
        persisted.state = RunState.RUNNING
        persisted.current_step = 0
        runs.save_with_event(persisted, "run_created", {})

        plans = PlanStore(plans_path, ttl_seconds=30)
        executed: list[str] = []
        response = TestClient(app_for(plans, runs, reviews, executed)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )
        assert response.status_code == 503, (field, response.text)
        assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
        assert executed == []
        after = runs.load(run_id)
        assert after is not None and getattr(after, field) == tampered_value
        assert after.steps[0].state == StepState.PENDING
        recovery = plans.reviewed_start_recovery(plan_id)
        assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
        plans.close()


def inverse_review_policy_enabled_is_pending(root: str, *, waiting: bool) -> None:
    name = "inverse-waiting" if waiting else "inverse-enabled"
    reviewed = template_run(two_reads=waiting)
    plans_path, plan_id, run_id, runs, reviews = prepare_pending(root, name, reviewed)
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.RUNNING
    if waiting:
        persisted.steps[0].state = StepState.SUCCEEDED
        persisted.steps[0].result = {"ok": True}
        persisted.current_step = 1
    runs.save_with_event(persisted, "run_created", {})
    reviews.configure(run_id, True)
    if waiting:
        reviews.set_waiting(
            run_id,
            completed_step_id=persisted.steps[0].id,
            completed_tool=persisted.steps[0].tool,
            window_start=1,
            window_end=2,
            removable_step_ids=[persisted.steps[1].id],
        )

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    state = reviews.get(run_id)
    assert state["enabled"] is True
    assert state["waiting"] is waiting
    after = runs.load(run_id)
    assert after is not None and after.state is RunState.RUNNING
    if waiting:
        assert after.current_step == 1
        assert after.steps[1].state == StepState.PENDING
    else:
        assert after.current_step == 0
        assert after.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


def waiting_confirmation_policy_mismatch_is_pending(
    root: str,
    *,
    accepted: bool,
    reviewed_reads: bool,
    stored_enabled: bool | None,
    stale_waiting: bool = False,
) -> None:
    name = (
        f"waiting-{'accepted' if accepted else 'pending'}-"
        f"review-{int(reviewed_reads)}-store-{stored_enabled}-waiting-{int(stale_waiting)}"
    )
    reviewed = template_run(two_reads=stale_waiting)
    plans_path = os.path.join(root, f"{name}-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(reviewed, review_reads=reviewed_reads))
    run_id = f"{name}-run"
    old.claim_reviewed_start(plan_id, run_id)
    if accepted:
        old.mark_reviewed_start_accepted(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, f"{name}-runs.db"))
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.WAITING_CONFIRMATION
    persisted.steps[0].state = StepState.WAITING_CONFIRMATION
    persisted.current_step = 0
    runs.save_with_event(persisted, "confirmation_required", {"step_id": persisted.steps[0].id})

    reviews = ReadReviewStore(os.path.join(root, f"{name}-reviews.db"))
    if stored_enabled is not None:
        reviews.configure(run_id, stored_enabled)
    if stale_waiting:
        assert stored_enabled is True
        reviews.set_waiting(
            run_id,
            completed_step_id=persisted.steps[0].id,
            completed_tool=persisted.steps[0].tool,
            window_start=1,
            window_end=2,
            removable_step_ids=[persisted.steps[1].id],
        )

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, (name, response.text)
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    after = runs.load(run_id)
    assert after is not None and after.state is RunState.WAITING_CONFIRMATION
    assert after.steps[0].state is StepState.WAITING_CONFIRMATION
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None
    assert recovery[0] == ("accepted" if accepted else "pending")
    assert recovery[1] == run_id
    state = reviews.get(run_id)
    if stored_enabled is None:
        assert state["enabled"] is False
    else:
        assert state["enabled"] is stored_enabled
    assert state["waiting"] is stale_waiting
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1j-")
execution_policy_flag_tamper_is_pending(root)
inverse_review_policy_enabled_is_pending(root, waiting=False)
inverse_review_policy_enabled_is_pending(root, waiting=True)

# A confirmation is resumable authority: policy corruption must fail closed for
# both pending crash recovery and an already-accepted replay.
for accepted in (False, True):
    waiting_confirmation_policy_mismatch_is_pending(
        root,
        accepted=accepted,
        reviewed_reads=True,
        stored_enabled=None,
    )
    waiting_confirmation_policy_mismatch_is_pending(
        root,
        accepted=accepted,
        reviewed_reads=True,
        stored_enabled=False,
    )
    waiting_confirmation_policy_mismatch_is_pending(
        root,
        accepted=accepted,
        reviewed_reads=False,
        stored_enabled=True,
    )

# A read checkpoint cannot coexist with confirmation authority even when the
# broad enabled bit matches review_reads=true.
waiting_confirmation_policy_mismatch_is_pending(
    root,
    accepted=True,
    reviewed_reads=True,
    stored_enabled=True,
    stale_waiting=True,
)

print("42 passed, 0 failed")
