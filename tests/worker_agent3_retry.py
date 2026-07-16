from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import Agent3Orchestrator, AgentRunStore, CapabilitySnapshot
from app.agent3.integration import V2ToolAdapter


class Tool:
    name = "rig_status"
    risk = "read"

    @staticmethod
    def human_summary(args):
        return "Læs rigstatus"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def propose(name, args, conversation_id=None, origin="local"):
        return {"status": "executed", "result": f"{origin}:{name}"}


fake = SimpleNamespace(REGISTRY={"rig_status": Tool()}, GATE=Gate())
adapter = V2ToolAdapter(fake)
store = AgentRunStore(os.path.join(tempfile.mkdtemp(prefix="agent3-retry-"), "runs.db"))
orch = Agent3Orchestrator(store, adapter.execute)
caps = CapabilitySnapshot(True, True, True, True, True, True)
app = FastAPI()
app.include_router(build_router(orch, adapter, lambda req, _adapter: caps))
client = TestClient(app)

first = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "brug RAG og tools",
        "mode": "cloud",
        "tools": True,
        "rag": True,
        "allow_rag_cloud": True,
        "allow_private_cloud": True,
        "cloud_ready": True,
        "plan": [{"tool": "rig_status", "args": {}}],
    },
)
assert first.status_code == 200, first.text
original = first.json()["run"]
assert original["route"]["uses_tools"] is True
assert original["route"]["uses_rag"] is True

retry = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "maliciously changed",
        "mode": "rig",
        "tools": False,
        "rag": False,
        "cloud_ready": True,
        "retry_of_run_id": original["id"],
        "plan": [{"tool": "does_not_exist", "args": {}}],
    },
)
assert retry.status_code == 200, retry.text
retried = retry.json()["run"]
assert retried["request"]["message"] == "brug RAG og tools"
assert retried["request"]["mode"] == "cloud"
assert retried["route"]["uses_tools"] is True
assert retried["route"]["uses_rag"] is True
assert retried["steps"][0]["tool"] == "rig_status"
print("6 passed, 0 failed")
