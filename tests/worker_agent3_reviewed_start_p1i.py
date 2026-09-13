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


def template_run(*, args: dict | None = None) -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="recover authority", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args=args or {},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
    )


def payload(*, review_reads=True, include_review_reads: bool = True) -> str:
    body = {
        "run": template_run().to_json(),
        "capabilities": asdict(
            CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
        ),
    }
    if include_review_reads:
        body["review_reads"] = review_reads
    return json.dumps(body, sort_keys=True)


def app_for(plans: PlanStore, run_store: AgentRunStore, review_store: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
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


def rewrite_embedded_run_id(runs: AgentRunStore, row_id: str, embedded_id: str) -> None:
    """Simulate partial restore/corruption where row key and payload id diverge."""
    with runs._lock:
        row = runs._conn.execute("SELECT payload FROM agent_runs WHERE id=?", (row_id,)).fetchone()
        assert row is not None
        body = json.loads(row[0])
        body["id"] = embedded_id
        runs._conn.execute(
            "UPDATE agent_runs SET payload=? WHERE id=?",
            (json.dumps(body, ensure_ascii=False, sort_keys=True), row_id),
        )
        runs._conn.commit()


def missing_pending_run_stays_ambiguous(root: str) -> None:
    plans_path = os.path.join(root, "missing-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=False))
    run_id = "missing-pending-run"
    old.claim_reviewed_start(plan_id, run_id)
    old_owner = old.start_owner
    old.close()

    plans = PlanStore(plans_path, ttl_seconds=30)
    runs = AgentRunStore(os.path.join(root, "missing-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "missing-reviews.db"))
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    assert runs.load(run_id) is None
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery == ("pending", run_id, old_owner)
    plans.close()


def invalid_review_reads_initial_is_refused(root: str) -> None:
    invalid_values = [None, 0, "", [], {}]
    for index, value in enumerate(invalid_values):
        plans = PlanStore(os.path.join(root, f"invalid-initial-{index}.db"), ttl_seconds=30)
        plan_id, _ = plans.save(payload(review_reads=value))
        runs = AgentRunStore(os.path.join(root, f"invalid-initial-runs-{index}.db"))
        reviews = ReadReviewStore(os.path.join(root, f"invalid-initial-reviews-{index}.db"))
        executed: list[str] = []
        response = TestClient(app_for(plans, runs, reviews, executed)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )
        assert response.status_code == 409, response.text
        assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
        assert executed == []
        recovery = plans.reviewed_start_recovery(plan_id)
        assert recovery is not None and recovery[0] == "refused"
        plans.close()

    plans = PlanStore(os.path.join(root, "invalid-initial-missing.db"), ttl_seconds=30)
    plan_id, _ = plans.save(payload(include_review_reads=False))
    runs = AgentRunStore(os.path.join(root, "invalid-initial-missing-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "invalid-initial-missing-reviews.db"))
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    assert executed == []
    plans.close()


def invalid_review_reads_recovery_stays_pending(root: str) -> None:
    plans_path = os.path.join(root, "invalid-recovery-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=None))
    run_id = "invalid-review-reads-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "invalid-recovery-runs.db"))
    persisted = template_run()
    persisted.id = run_id
    persisted.state = RunState.RUNNING
    persisted.current_step = 0
    runs.save_with_event(persisted, "run_created", {})
    reviews = ReadReviewStore(os.path.join(root, "invalid-recovery-reviews.db"))
    reviews.configure(run_id, True)

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    persisted_after = runs.load(run_id)
    assert persisted_after is not None
    assert persisted_after.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


def mismatched_run_never_advances(root: str) -> None:
    plans_path = os.path.join(root, "mismatch-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=False))
    run_id = "mismatched-bound-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "mismatch-runs.db"))
    tampered = template_run(args={"path": "tampered"})
    tampered.id = run_id
    tampered.state = RunState.RUNNING
    tampered.current_step = 0
    runs.save_with_event(tampered, "run_created", {})
    reviews = ReadReviewStore(os.path.join(root, "mismatch-reviews.db"))
    reviews.configure(run_id, False)

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    persisted = runs.load(run_id)
    assert persisted is not None
    assert persisted.steps[0].args == {"path": "tampered"}
    assert persisted.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


def embedded_run_id_mismatch_never_borrows_reserved_authority(root: str) -> None:
    for accepted in (False, True):
        suffix = "accepted" if accepted else "pending"
        plans_path = os.path.join(root, f"embedded-id-{suffix}-plans.db")
        old = PlanStore(plans_path, ttl_seconds=30)
        plan_id, _ = old.save(payload(review_reads=False))
        run_id = f"reserved-{suffix}-run"
        old.claim_reviewed_start(plan_id, run_id)
        if accepted:
            old.mark_reviewed_start_accepted(plan_id, run_id)
        old.close()

        runs = AgentRunStore(os.path.join(root, f"embedded-id-{suffix}-runs.db"))
        persisted = template_run()
        persisted.id = run_id
        persisted.state = RunState.RUNNING
        runs.save_with_event(persisted, "run_created", {})
        rewrite_embedded_run_id(runs, run_id, f"foreign-{suffix}-run")
        reviews = ReadReviewStore(os.path.join(root, f"embedded-id-{suffix}-reviews.db"))
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
        assert recovery is not None and recovery[0] == ("accepted" if accepted else "pending")
        assert recovery[1] == run_id
        plans.close()


def accepted_waiting_confirmation_requires_reviewed_identity(root: str) -> None:
    plans = PlanStore(os.path.join(root, "accepted-waiting-plans.db"), ttl_seconds=30)
    plan_id, _ = plans.save(payload(review_reads=False))
    run_id = "accepted-waiting-run"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.mark_reviewed_start_accepted(plan_id, run_id)

    runs = AgentRunStore(os.path.join(root, "accepted-waiting-runs.db"))
    tampered = template_run(args={"path": "unreviewed-later-step"})
    tampered.id = run_id
    tampered.state = RunState.WAITING_CONFIRMATION
    tampered.steps[0].state = StepState.WAITING_CONFIRMATION
    runs.save_with_event(tampered, "confirmation_required", {"step_id": tampered.steps[0].id})
    reviews = ReadReviewStore(os.path.join(root, "accepted-waiting-reviews.db"))
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
    assert persisted.state == RunState.WAITING_CONFIRMATION
    assert persisted.steps[0].args == {"path": "unreviewed-later-step"}
    assert plans.reviewed_start_recovery(plan_id)[0] == "accepted"
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1i-")
missing_pending_run_stays_ambiguous(root)
invalid_review_reads_initial_is_refused(root)
invalid_review_reads_recovery_stays_pending(root)
mismatched_run_never_advances(root)
embedded_run_id_mismatch_never_borrows_reserved_authority(root)
accepted_waiting_confirmation_requires_reviewed_identity(root)

print("36 passed, 0 failed")
