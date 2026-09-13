from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRun, AgentRunStore, AgentStep, CapabilitySnapshot, RiskClass, RouteKind, RoutePlan, StepState, TurnRequest
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def stored_plan(plan_store: PlanStore, *, idempotent: bool) -> tuple[str, str]:
    step = AgentStep(tool="recovery_probe", args={}, risk=RiskClass.READ, idempotent=idempotent, summary="recovery probe")
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[step],
    )
    envelope = {
        "run": template.to_json(),
        "capabilities": asdict(CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)),
        "review_reads": False,
    }
    plan_id, _ = plan_store.save(json.dumps(envelope, sort_keys=True))
    return plan_id, template.to_json()


def client_for(plan_store: PlanStore, run_store: AgentRunStore, executed: list[str]) -> TestClient:
    orchestrator = Agent3Orchestrator(run_store, lambda step: executed.append(step.tool) or {"ok": True})
    app = FastAPI()
    app.include_router(build_planner_router(adapter, SimpleNamespace(), orchestrator=orchestrator, plan_store=plan_store))
    return TestClient(app)


def recover_snapshot(*, executing: bool):
    root = tempfile.mkdtemp(prefix="agent3-reviewed-start-reconcile-")
    plans_path = os.path.join(root, "plans.db")
    runs_path = os.path.join(root, "runs.db")
    first = PlanStore(plans_path, ttl_seconds=30)
    plan_id, template_raw = stored_plan(first, idempotent=not executing)
    run_id = "reserved-executing" if executing else "reserved-pending"
    first.claim_reviewed_start(plan_id, run_id)

    crash_run = AgentRun.from_json(template_raw)
    crash_run.id = run_id
    if executing:
        crash_run.steps[0].state = StepState.EXECUTING
    run_store = AgentRunStore(runs_path)
    run_store.save_with_event(crash_run, "run_created", {"crash_fixture": True})
    first.close()

    second = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = client_for(second, run_store, executed).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert response.status_code == 200, response.text
    recovery = second.reviewed_start_recovery(plan_id)
    second.close()
    return response.json(), executed, recovery


pending, pending_executed, pending_recovery = recover_snapshot(executing=False)
assert pending["run"]["id"] == "reserved-pending"
assert pending["run"]["state"] == "completed"
assert pending_executed == ["recovery_probe"]
assert pending_recovery is not None and pending_recovery[:2] == ("accepted", "reserved-pending")

interrupted, interrupted_executed, interrupted_recovery = recover_snapshot(executing=True)
assert interrupted["run"]["id"] == "reserved-executing"
assert interrupted["run"]["state"] == "blocked"
assert interrupted["run"]["steps"][0]["state"] == "blocked"
assert "interrupted" in (interrupted["run"]["error"] or "").lower()
assert interrupted_executed == []
assert interrupted_recovery is not None and interrupted_recovery[:2] == ("accepted", "reserved-executing")

print("8 passed, 0 failed")
