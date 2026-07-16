from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import AgentRunStore, CapabilitySnapshot
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.replan_planner import TypedReadReplanPlanner
from app.agent3.replan_preview_api import build_replan_preview_router
from app.agent3.replan_review import ReviewAwareReplanPreviewService
from app.agent3.replan_runtime import PersistentReadReplanner, ReplanJournal
from app.agent3.replanner import ReadSuffixReplanner
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


class Tool:
    def __init__(self, name: str, risk: str):
        self.name = name
        self.risk = risk
        self.description = name
        self.params = {"type": "object", "properties": {}}

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name: str) -> bool:
        return name in {"rig_status", "list_models", "note_append"}


class Executor:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, step):
        self.calls.append(step.tool)
        return {"tool": step.tool, "ok": True}


calls = {"planner": 0}


async def scripted_chat(messages, model):
    calls["planner"] += 1
    assert model == "local-replanner"
    assert "note_append" not in messages[0]["content"]
    return '{"steps":[{"tool":"rig_status","args":{"detail":true}}],"rationale":"Replace the remaining read with one fresh status call"}'


root = tempfile.mkdtemp(prefix="agent3-review-api-apply-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
review_store = ReadReviewStore(os.path.join(root, "reviews.db"))
executor = Executor()
orchestrator = ReviewingAgent3Orchestrator(run_store, executor, review_store)
tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read"),
        "list_models": Tool("list_models", "read"),
        "note_append": Tool("note_append", "write"),
    },
    GATE=Gate(),
)
adapter = V2ToolAdapter(tools)
policy = ReadSuffixReplanner(max_steps=8, max_replans=3)
persistent = PersistentReadReplanner(
    run_store,
    ReplanJournal(os.path.join(root, "journal.db")),
    policy,
)
service = ReviewAwareReplanPreviewService(
    run_store,
    persistent,
    TypedReadReplanPlanner(adapter, policy, chat_fn=scripted_chat),
    PlanStore(os.path.join(root, "previews.db"), ttl_seconds=300),
    review_store=review_store,
)


def caps(_req, _adapter):
    return CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=True,
        cloud_ready=False,
        rag_ready=True,
    )


app = FastAPI()
app.include_router(
    build_router(
        orchestrator,
        adapter,
        capability_provider=caps,
        replan_service=persistent,
    )
)
app.include_router(build_replan_preview_router(service))
client = TestClient(app)

started = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "review and replan remaining reads",
        "mode": "rig",
        "tools": True,
        "review_reads": True,
        "conversation_id": "conv-review-apply",
        "plan": [
            {"tool": "rig_status", "args": {}},
            {"tool": "list_models", "args": {}},
            {"tool": "note_append", "args": {"text": "immutable-tail"}},
        ],
    },
)
assert started.status_code == 200, started.text
start_payload = started.json()
run_id = start_payload["run"]["id"]
old_read_id = start_payload["run"]["steps"][1]["id"]
write_id = start_payload["run"]["steps"][2]["id"]
assert executor.calls == ["rig_status"]
assert start_payload["read_review"]["waiting"] is True
assert start_payload["read_review"]["removable_step_ids"] == [old_read_id]

preview_response = client.post(
    f"/experimental/agent3/runs/{run_id}/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert preview_response.status_code == 200, preview_response.text
preview = preview_response.json()
assert preview["executed"] is False
assert preview["window"]["removable_step_ids"] == [old_read_id]
assert preview["window"]["immutable_tail_ids"] == [write_id]
assert preview["plan"][0]["tool"] == "rig_status"
assert calls["planner"] == 1
assert executor.calls == ["rig_status"]

applied_response = client.post(
    f"/experimental/agent3/replan-previews/{preview['preview_id']}/apply"
)
assert applied_response.status_code == 200, applied_response.text
applied = applied_response.json()
assert applied["run"]["current_step"] == 1
assert applied["run"]["state"] == "running"
assert [step["tool"] for step in applied["run"]["steps"]] == [
    "rig_status",
    "rig_status",
    "note_append",
]
new_read_id = applied["run"]["steps"][1]["id"]
assert new_read_id != old_read_id
assert applied["run"]["steps"][2]["id"] == write_id
assert applied["run"]["steps"][2]["args"] == {"text": "immutable-tail"}
assert executor.calls == ["rig_status"]
assert calls["planner"] == 1

loaded_response = client.get(f"/experimental/agent3/runs/{run_id}")
assert loaded_response.status_code == 200, loaded_response.text
loaded = loaded_response.json()
assert loaded["run"]["current_step"] == 1
assert loaded["read_review"]["enabled"] is True
assert loaded["read_review"]["waiting"] is True
assert loaded["read_review"]["window_start"] == 1
assert loaded["read_review"]["window_end"] == 2
assert loaded["read_review"]["removable_step_ids"] == [new_read_id]
assert old_read_id not in loaded["read_review"]["removable_step_ids"]
assert executor.calls == ["rig_status"]

events = client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"]
rebound = [event for event in events if event["kind"] == "replan_review_rebound"]
assert len(rebound) == 1
assert rebound[0]["payload"]["execution_resumed"] is False
assert rebound[0]["payload"]["previous_removable_step_ids"] == [old_read_id]
assert rebound[0]["payload"]["removable_step_ids"] == [new_read_id]

print("30 passed, 0 failed")
