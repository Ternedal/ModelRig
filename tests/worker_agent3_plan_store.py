from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore, PlanStoreError
from app.agent3.planner import TypedPlanner, build_planner_router
from app.agent3 import capability_probe as _probe  # noqa: E402

_probe.measure = lambda **kw: {
    "worker_ready": True,
    "rig_reachable": True,
    "rag_ready": True,
    "measured_at": 0.0,
}

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class Tool:
    name = "note_append"
    risk = "write"
    impact = "write"
    description = "Skriv en note"
    params = {"type": "object", "properties": {"text": {"type": "string"}}}
    isolate = False
    env_allow = ()
    schedulable = True
    unschedulable_because = ""
    sensitivity = "private"
    cancellation = "none"
    idempotent = False
    network = "none"
    network_destinations = ()

    @staticmethod
    def human_summary(args):
        return f"Skriv: {args.get('text')}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name == "note_append"

    @staticmethod
    def propose(*_args, **_kwargs):
        raise AssertionError("a write must wait for Agent 3.0 confirmation")


gate = Gate()
adapter = V2ToolAdapter(
    SimpleNamespace(REGISTRY={"note_append": Tool()}, GATE=gate)
)


async def planned(_messages, _model):
    return '{"steps":[{"tool":"note_append","args":{"text":"original"}}],"rationale":"test"}'


root = tempfile.mkdtemp(prefix="agent3-plan-store-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
plan_store = PlanStore(os.path.join(root, "plans.db"), ttl_seconds=60)
orch = Agent3Orchestrator(run_store, adapter.execute)
app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        TypedPlanner(adapter, chat_fn=planned),
        orchestrator=orch,
        plan_store=plan_store,
    )
)
client = TestClient(app)

preview = client.post("/experimental/agent3/plan", json={"message": "gem original"})
check(preview.status_code == 200, "preview succeeds")
plan_id = preview.json().get("plan_id")
check(bool(plan_id), "preview returns a persistent plan_id")
check(preview.json()["plan"][0]["args"]["text"] == "original", "reviewed args are visible")

start = client.post(f"/experimental/agent3/plans/{plan_id}/start", json={"plan": "changed"})
check(start.status_code == 200, "reviewed plan starts without replacement payload")
run = start.json()["run"]
check(run["state"] == "waiting_confirmation", "write still waits for confirmation")
check(run["steps"][0]["args"]["text"] == "original", "stored reviewed args remain authoritative")

reused = client.post(f"/experimental/agent3/plans/{plan_id}/start")
check(reused.status_code == 409, "plan_id is single-use")

expiry_path = os.path.join(root, "expiry.db")
expiry_store = PlanStore(expiry_path, ttl_seconds=30)
expired_id, _ = expiry_store.save("payload")
with sqlite3.connect(expiry_path) as connection:
    connection.execute(
        "UPDATE agent_plans SET expires_at=? WHERE id=?",
        (time.time() - 1, expired_id),
    )
try:
    expiry_store.consume(expired_id)
    expired = False
except PlanStoreError:
    expired = True
check(expired, "expired plan is refused")

replay_store = PlanStore(os.path.join(root, "replay.db"), ttl_seconds=30)
accepted_id, _ = replay_store.save("accepted")
replay_store.consume(accepted_id)
check(replay_store.start_result(accepted_id) == ("pending", None), "consumed plan is pending before run binding")
replay_store.bind_pending_run(accepted_id, "run-123")
check(replay_store.start_result(accepted_id) == ("pending", "run-123"), "bound run remains pending before executor acceptance")
replay_store.mark_start_accepted(accepted_id, "run-123")
check(replay_store.start_result(accepted_id) == ("accepted", "run-123"), "accepted plan remembers its exact task run")
replay_store.bind_pending_run(accepted_id, "run-123")
try:
    replay_store.bind_pending_run(accepted_id, "run-456")
    rebound = True
except PlanStoreError:
    rebound = False
check(not rebound, "accepted plan cannot bind a second task run")
refused_id, _ = replay_store.save("refused")
replay_store.consume(refused_id)
replay_store.bind_pending_run(refused_id, "run-refused")
replay_store.mark_start_refused(refused_id)
check(replay_store.start_result(refused_id) == ("refused", None), "refused plan remains definitively refused")
check(replay_store.purge() == 0, "consumed replay records survive until expiry")
replay_store.close()

owner_path = os.path.join(root, "owner-recovery.db")
owner_first = PlanStore(owner_path, ttl_seconds=30)
owner_plan, _ = owner_first.save("owner")
owner_first.consume(owner_plan)
owner_first.bind_pending_run(owner_plan, "run-owner")
owner_recovery = owner_first.start_recovery(owner_plan)
old_owner = owner_recovery[2] if owner_recovery is not None else None
check(
    owner_recovery == ("pending", "run-owner", owner_first.start_owner),
    "bound Start persists its opaque worker-generation owner",
)
owner_first.close()
owner_second = PlanStore(owner_path, ttl_seconds=30)
check(owner_second.start_owner != old_owner, "reopening the store creates a new worker generation")
check(
    owner_second.start_recovery(owner_plan) == ("pending", "run-owner", old_owner),
    "worker restart preserves the previous generation on the pending run",
)
claimed_state = owner_second.claim_start_recovery(owner_plan, "run-owner", old_owner)
check(
    claimed_state == "pending"
    and owner_second.start_recovery(owner_plan) == (
        "pending",
        "run-owner",
        owner_second.start_owner,
    ),
    "dead-owner recovery CAS transfers only the same pending run",
)
check(
    owner_second.release_start_recovery_claim(owner_plan, "run-owner")
    and owner_second.start_recovery(owner_plan) == ("pending", "run-owner", None),
    "failed recovery submission can release the generation claim for retry",
)
owner_second.close()

plan_store.close()
expiry_store.close()
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
