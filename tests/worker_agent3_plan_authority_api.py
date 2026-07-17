from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import StartReq, build_router
from app.agent3.core import Agent3Orchestrator, AgentRunStore, CapabilitySnapshot, TurnRequest
from app.agent3.integration import PlannedToolCall, V2ToolAdapter
from app.agent3.routing import StrictTurnRouter


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
store = AgentRunStore(os.path.join(tempfile.mkdtemp(prefix="agent3-authority-"), "runs.db"))
orchestrator = Agent3Orchestrator(store, adapter.execute)
caps = CapabilitySnapshot(True, True, True, True, True, True)

request = TurnRequest("brug RAG og tools", mode="cloud", tools=True, rag=True, allow_rag_cloud=True)
route = StrictTurnRouter().route(request, caps)
steps = adapter.build_steps([PlannedToolCall("rig_status", {})], route, None)
original = orchestrator.start_with_steps(request, caps, steps, allow_private_cloud=True)

app = FastAPI()
app.include_router(build_router(orchestrator, adapter, lambda req, _adapter: caps))
client = TestClient(app)

assert "plan" not in StartReq.model_fields
blocked = client.post(
    "/experimental/agent3/runs",
    json={"message": "status", "plan": [{"tool": "rig_status", "args": {}}]},
)
assert blocked.status_code == 405, blocked.text

rejected = client.post(
    f"/experimental/agent3/runs/{original.id}/retry",
    json={"cloud_ready": True, "plan": [{"tool": "does_not_exist", "args": {}}]},
)
assert rejected.status_code == 422, rejected.text

retried_response = client.post(
    f"/experimental/agent3/runs/{original.id}/retry",
    json={"cloud_ready": True},
)
assert retried_response.status_code == 200, retried_response.text
retried = retried_response.json()["run"]
assert retried["id"] != original.id
assert retried["request"]["message"] == request.message
assert retried["request"]["mode"] == request.mode
assert retried["route"]["kind"] == original.route.kind.value
assert [step["tool"] for step in retried["steps"]] == ["rig_status"]
print("8 passed, 0 failed")
