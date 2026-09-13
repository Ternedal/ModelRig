from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "worker/app/agent3/planner.py",
    '''    def _reconcile_reviewed_start_run(run_id: str) -> AgentRun:\n        existing = orchestrator.store.load(run_id)\n''',
    '''    def _reconcile_reviewed_start_run(\n        run_id: str,\n        *,\n        review_reads: bool,\n    ) -> AgentRun:\n        existing = orchestrator.store.load(run_id)\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        # Reviewed Start recovery must restore human review authority before\n        # advancing. This covers both an already-durable waiting checkpoint and\n        # the cross-store crash windows where a READ succeeded but set_waiting()\n        # had not yet reached the review DB.\n        if reviewing:\n            checkpointed = orchestrator.recover_read_review_checkpoint_if_due(run_id)\n            if checkpointed is not None:\n                return checkpointed\n        try:\n            return orchestrator.advance(run_id)\n''',
    '''        # The materialized reviewed plan is the authority for whether reads\n        # require human review. The separate review DB may be missing or only\n        # partially restored after a crash/restore. If the plan requires review\n        # but that policy row is absent/disabled, recovery must stop before any\n        # advance() can execute remaining reads. A client-side envelope mismatch\n        # check would happen too late because side effects could already exist.\n        if review_reads:\n            if not reviewing:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed read policy is unavailable; recovery remains ambiguous",\n                    status_code=503,\n                )\n            review_state = orchestrator.review_store.get(run_id)\n            if not review_state["enabled"]:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed read policy is missing; recovery remains ambiguous",\n                    status_code=503,\n                )\n            checkpointed = orchestrator.recover_read_review_checkpoint_if_due(run_id)\n            if checkpointed is not None:\n                return checkpointed\n        try:\n            return orchestrator.advance(run_id)\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''            payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n            if existing is not None:\n                reconciled = _reconcile_reviewed_start_run(reserved_run_id)\n                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n                stored = json.loads(payload)\n                return _reviewed_start_response(plan_id, stored, reconciled)\n''',
    '''            payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n            if existing is not None:\n                # Parse only the bounded policy bit before reconciliation. If a\n                # materialization that already has a persisted run is unreadable,\n                # its authority is ambiguous: do not advance and do not convert it\n                # into a definitive refusal that clients could clear.\n                try:\n                    recovery_envelope = json.loads(payload)\n                    if not isinstance(recovery_envelope, dict):\n                        raise TypeError("reviewed Start materialization must be an object")\n                    recovered_review_reads = bool(\n                        recovery_envelope.get("review_reads", False)\n                    )\n                except (TypeError, json.JSONDecodeError, ValueError) as exc:\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "persisted reviewed Start policy is unreadable; recovery remains ambiguous",\n                        status_code=503,\n                    ) from exc\n                reconciled = _reconcile_reviewed_start_run(\n                    reserved_run_id,\n                    review_reads=recovered_review_reads,\n                )\n                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n                stored = recovery_envelope\n                return _reviewed_start_response(plan_id, stored, reconciled)\n''',
)

Path("tests/worker_agent3_reviewed_start_p1f.py").write_text(r'''from __future__ import annotations

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
''', encoding="utf-8")

print("reviewed Start P1f patch staged")
