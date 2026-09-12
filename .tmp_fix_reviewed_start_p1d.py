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
    '''        if existing.state is not RunState.RUNNING:\n            return existing\n        try:\n            return orchestrator.advance(run_id)\n''',
    '''        if existing.state is not RunState.RUNNING:\n            return existing\n        # A waiting read-review checkpoint is explicit human authority. A retry\n        # that is only recovering a previously ambiguous Start must never consume\n        # that checkpoint by calling advance() without an expected review step.\n        if reviewing and orchestrator.review_store.get(run_id)["waiting"]:\n            return existing\n        try:\n            return orchestrator.advance(run_id)\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''            if state == "accepted":\n                if existing is None:\n                    raise _reviewed_start_error(\n                        "reviewed_start_refused",\n                        "accepted reviewed Start is missing its bound run",\n                    )\n                stored = json.loads(\n''',
    '''            if state == "accepted":\n                if existing is None:\n                    # Acceptance proves this exact reserved run was materialized at\n                    # least once and may already have produced side effects. Missing\n                    # run storage is therefore ambiguous/corrupt recovery, never a\n                    # definitive refusal that would let clients clear authority.\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "accepted reviewed Start is missing its bound run; recovery remains ambiguous",\n                        status_code=503,\n                    )\n                stored = json.loads(\n''',
)

Path("tests/worker_agent3_reviewed_start_p1d.py").write_text(r'''from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RouteKind,
    RoutePlan,
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


def envelope_payload(*, review_reads: bool, steps: list[AgentStep]) -> str:
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
    )
    return json.dumps(
        {
            "run": template.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(
                    rig_reachable=True,
                    worker_ready=True,
                    tools_ready=True,
                )
            ),
            "review_reads": review_reads,
        },
        sort_keys=True,
    )


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1d-")

# P1: recovery of a pending RUNNING reviewed Start must preserve an active
# read-review checkpoint instead of consuming it through advance().
plans_path = os.path.join(root, "waiting-plans.db")
runs_path = os.path.join(root, "waiting-runs.db")
reviews_path = os.path.join(root, "waiting-reviews.db")
steps = [
    AgentStep(tool="read_one", args={}, risk=RiskClass.READ, idempotent=True, summary="read one"),
    AgentStep(tool="read_two", args={}, risk=RiskClass.READ, idempotent=True, summary="read two"),
]
first_plans = PlanStore(plans_path, ttl_seconds=30)
plan_id, _ = first_plans.save(envelope_payload(review_reads=True, steps=steps))
reserved_run_id = "reserved-waiting-review"
first_plans.claim_reviewed_start(plan_id, reserved_run_id)

run_store = AgentRunStore(runs_path)
review_store = ReadReviewStore(reviews_path)
executed: list[str] = []
reviewing_orch = ReviewingAgent3Orchestrator(
    run_store,
    lambda step: executed.append(step.tool) or {"ok": True},
    review_store,
)
waiting = reviewing_orch.start_with_steps(
    TurnRequest(message="recover", mode="rig", tools=True),
    CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True),
    steps,
    review_reads=True,
    run_id=reserved_run_id,
)
assert waiting.id == reserved_run_id
assert waiting.state.value == "running"
assert review_store.get(reserved_run_id)["waiting"] is True
assert executed == ["read_one"]
first_plans.close()

second_plans = PlanStore(plans_path, ttl_seconds=30)
app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        SimpleNamespace(),
        orchestrator=reviewing_orch,
        plan_store=second_plans,
    )
)
response = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
assert response.status_code == 200, response.text
body = response.json()
assert body["run"]["id"] == reserved_run_id
assert body["run"]["state"] == "running"
assert body["read_review"]["waiting"] is True
assert review_store.get(reserved_run_id)["waiting"] is True
assert executed == ["read_one"]
assert second_plans.reviewed_start_recovery(plan_id)[:2] == ("accepted", reserved_run_id)
second_plans.close()


# P1: accepted authority with missing run storage is ambiguous. It must remain
# fail-closed/pending, never become reviewed_start_refused.
missing_plans_path = os.path.join(root, "missing-plans.db")
missing_runs_path = os.path.join(root, "missing-runs.db")
missing_steps = [
    AgentStep(tool="read_probe", args={}, risk=RiskClass.READ, idempotent=True, summary="probe")
]
missing_plans = PlanStore(missing_plans_path, ttl_seconds=30)
missing_plan_id, _ = missing_plans.save(
    envelope_payload(review_reads=False, steps=missing_steps)
)
missing_run_id = "accepted-but-missing"
missing_plans.claim_reviewed_start(missing_plan_id, missing_run_id)
missing_plans.mark_reviewed_start_accepted(missing_plan_id, missing_run_id)
ordinary_orch = Agent3Orchestrator(
    AgentRunStore(missing_runs_path),
    lambda step: {"ok": True},
)
missing_app = FastAPI()
missing_app.include_router(
    build_planner_router(
        adapter,
        SimpleNamespace(),
        orchestrator=ordinary_orch,
        plan_store=missing_plans,
    )
)
missing_response = TestClient(missing_app).post(
    f"/experimental/agent3/plans/{missing_plan_id}/start"
)
assert missing_response.status_code == 503, missing_response.text
assert missing_response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
assert missing_plans.reviewed_start_recovery(missing_plan_id)[:2] == (
    "accepted",
    missing_run_id,
)
missing_plans.close()

print("16 passed, 0 failed")
''', encoding="utf-8")

print("reviewed Start P1d patch staged")
