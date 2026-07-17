from __future__ import annotations

import os
import tempfile
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore, PlanStoreError
from app.agent3.planner import TypedPlanner, build_planner_router
# The planner now plans against a rig it MEASURES (F-302, completed in 1.58.73:
# the 1.58.67 fix reached api.py and capability_graph_api.py and missed this
# one). There is no Ollama in CI, so an honest probe reports the rig
# unreachable and the planner correctly refuses to plan rig work against it.
# This test is about planning, not about whether Ollama is up -- so state the
# assumption instead of inheriting it.
from app.agent3 import capability_probe as _probe  # noqa: E402

_probe.measure = lambda **kw: {  # type: ignore[assignment]
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
    description = "Skriv en note"
    params = {"type": "object", "properties": {"text": {"type": "string"}}}

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
fake = SimpleNamespace(REGISTRY={"note_append": Tool()}, GATE=gate)
adapter = V2ToolAdapter(fake)


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
check(start.status_code == 200, "reviewed plan starts without accepting a replacement payload")
run = start.json()["run"]
check(run["state"] == "waiting_confirmation", "write still waits for a fresh run confirmation")
check(run["steps"][0]["args"]["text"] == "original", "stored reviewed args are the args in the run")

reused = client.post(f"/experimental/agent3/plans/{plan_id}/start")
check(reused.status_code == 409, "plan_id is single-use")

expiry_store = PlanStore(os.path.join(root, "expiry.db"), ttl_seconds=30)
expired_id, _ = expiry_store.save("payload")
expiry_store._conn.execute("UPDATE agent_plans SET expires_at=? WHERE id=?", (time.time() - 1, expired_id))
expiry_store._conn.commit()
try:
    expiry_store.consume(expired_id)
    expired = False
except PlanStoreError:
    expired = True
check(expired, "expired plan is refused")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
