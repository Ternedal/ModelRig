from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
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
    RunState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def envelope_payload() -> str:
    step = AgentStep(
        tool="recovery_probe",
        args={},
        risk=RiskClass.READ,
        idempotent=True,
        summary="recovery probe",
    )
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[step],
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
            "review_reads": False,
        },
        sort_keys=True,
    )


# P1: a persisted BLOCKED run is already terminal authority. Recovery must publish
# it as-is instead of feeding it to advance(), which only finalizes RUNNING runs.
root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1c-")
plans_path = os.path.join(root, "blocked-plans.db")
runs_path = os.path.join(root, "blocked-runs.db")
first = PlanStore(plans_path, ttl_seconds=30)
plan_id, _ = first.save(envelope_payload())
run_id = "reserved-blocked"
first.claim_reviewed_start(plan_id, run_id)
run_store = AgentRunStore(runs_path)
blocked = AgentRun(
    request=TurnRequest(message="recover", mode="rig", tools=True),
    route=RoutePlan(RouteKind.UNAVAILABLE, "capability drift", False, False, False, False),
    steps=[],
    state=RunState.BLOCKED,
    id=run_id,
    error="capability drift",
)
run_store.save_with_event(blocked, "run_blocked", {"reason": "capability drift"})
first.close()

second = PlanStore(plans_path, ttl_seconds=30)
executed: list[str] = []
orch = Agent3Orchestrator(run_store, lambda step: executed.append(step.tool) or {"ok": True})
app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        SimpleNamespace(),
        orchestrator=orch,
        plan_store=second,
    )
)
response = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
assert response.status_code == 200, response.text
assert response.json()["run"]["id"] == run_id
assert response.json()["run"]["state"] == "blocked"
assert response.json()["run"]["error"] == "capability drift"
assert executed == []
assert second.reviewed_start_recovery(plan_id)[:2] == ("accepted", run_id)
second.close()


# P1: wall-clock retention must not transmute pending/accepted reviewed Start
# authority into refusal, and purge must retain the immutable plan payload it
# needs to replay the exact plan/run binding after a long client outage.
retention_path = os.path.join(root, "reviewed-retention.db")
store = PlanStore(retention_path, ttl_seconds=30)
accepted_id, _ = store.save("accepted-payload")
store.claim_reviewed_start(accepted_id, "accepted-run")
store.mark_reviewed_start_accepted(accepted_id, "accepted-run")
pending_id, _ = store.save("pending-payload")
store.claim_reviewed_start(pending_id, "pending-run")
refused_id, _ = store.save("refused-payload")
store.claim_reviewed_start(refused_id, "refused-run")
store.mark_reviewed_start_refused(refused_id, "refused-run")
with sqlite3.connect(retention_path) as connection:
    expired = time.time() - 1
    connection.execute(
        "UPDATE agent_reviewed_starts SET expires_at=? WHERE plan_id IN (?,?,?)",
        (expired, accepted_id, pending_id, refused_id),
    )
    connection.execute(
        "UPDATE agent_plans SET expires_at=? WHERE id IN (?,?,?)",
        (expired, accepted_id, pending_id, refused_id),
    )
    connection.commit()
store.close()

reopened = PlanStore(retention_path, ttl_seconds=30)
accepted = reopened.reviewed_start_recovery(accepted_id)
pending = reopened.reviewed_start_recovery(pending_id)
assert accepted is not None and accepted[:2] == ("accepted", "accepted-run")
assert pending is not None and pending[:2] == ("pending", "pending-run")
assert reopened.reviewed_start_materialization(accepted_id, "accepted-run") == "accepted-payload"
assert reopened.reviewed_start_materialization(pending_id, "pending-run") == "pending-payload"
assert reopened.reviewed_start_recovery(refused_id) is None
with sqlite3.connect(retention_path) as connection:
    active_rows = connection.execute(
        "SELECT id FROM agent_plans WHERE id IN (?,?) ORDER BY id",
        (accepted_id, pending_id),
    ).fetchall()
    refused_rows = connection.execute(
        "SELECT id FROM agent_plans WHERE id=?",
        (refused_id,),
    ).fetchall()
assert len(active_rows) == 2
assert refused_rows == []
reopened.close()

print("14 passed, 0 failed")
