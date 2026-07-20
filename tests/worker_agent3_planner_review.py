from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import TypedPlanner, build_planner_router
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator
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


class Tool:
    risk = "read"
    impact = "read"
    description = "read tool"
    params = {"type": "object", "properties": {}}
    isolate = False
    env_allow = ()
    schedulable = True
    unschedulable_because = ""
    sensitivity = "operational"
    cancellation = "none"
    idempotent = True
    network = "none"
    network_destinations = ()

    def __init__(self, name):
        self.name = name

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name in {"rig_status", "list_models"}


async def chat(_messages, _model):
    return (
        '{"steps":['
        '{"tool":"rig_status","args":{}},'
        '{"tool":"list_models","args":{}}'
        ']}'
    )


root = tempfile.mkdtemp(prefix="agent3-planner-review-")
adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={
            "rig_status": Tool("rig_status"),
            "list_models": Tool("list_models"),
        },
        GATE=Gate(),
    )
)
run_store = AgentRunStore(os.path.join(root, "runs.db"))
review_store = ReadReviewStore(os.path.join(root, "reviews.db"))
executed = []


def execute(step):
    executed.append(step.tool)
    return {"tool": step.tool}


orchestrator = ReviewingAgent3Orchestrator(
    run_store,
    execute,
    review_store,
)
app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        TypedPlanner(adapter, chat_fn=chat),
        orchestrator=orchestrator,
        plan_store=PlanStore(os.path.join(root, "plans.db")),
    )
)
client = TestClient(app)

preview = client.post(
    "/experimental/agent3/plan",
    json={"message": "check rig", "mode": "rig", "review_reads": True},
)
assert preview.status_code == 200, preview.text
preview_body = preview.json()
assert preview_body["review_reads"] is True
assert preview_body["executed"] is False
assert executed == []

started = client.post(
    f"/experimental/agent3/plans/{preview_body['plan_id']}/start"
)
assert started.status_code == 200, started.text
body = started.json()
assert body["review_reads"] is True
assert body["read_review"]["enabled"] is True
assert body["read_review"]["waiting"] is True
assert body["run"]["current_step"] == 1
assert executed == ["rig_status"]
assert body["read_review"]["removable_step_ids"] == [
    body["run"]["steps"][1]["id"]
]

assert client.post(
    f"/experimental/agent3/plans/{preview_body['plan_id']}/start"
).status_code == 409

# Without explicit opt-in, the reviewed runtime retains the old contiguous-read
# behavior and returns a disabled review receipt.
plain_preview = client.post(
    "/experimental/agent3/plan",
    json={"message": "check rig normally", "mode": "rig"},
)
assert plain_preview.status_code == 200, plain_preview.text
plain_preview_body = plain_preview.json()
assert plain_preview_body["review_reads"] is False
plain = client.post(
    f"/experimental/agent3/plans/{plain_preview_body['plan_id']}/start"
)
assert plain.status_code == 200, plain.text
plain_body = plain.json()
assert plain_body["review_reads"] is False
assert plain_body["read_review"]["enabled"] is False
assert plain_body["read_review"]["waiting"] is False
assert plain_body["run"]["state"] == "completed"
assert plain_body["run"]["current_step"] == 2
assert executed[-2:] == ["rig_status", "list_models"]

print("19 passed, 0 failed")
