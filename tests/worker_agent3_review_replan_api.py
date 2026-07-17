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
from app.agent3.replan_preview import ReplanPreviewService
from app.agent3.replan_preview_api import build_replan_preview_router
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
    def is_enabled(name):
        return name in {"rig_status", "list_models", "current_datetime", "note_append"}

    @staticmethod
    def propose(*_args, **_kwargs):
        raise AssertionError("the test orchestrator owns execution")


tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read"),
        "list_models": Tool("list_models", "read"),
        "current_datetime": Tool("current_datetime", "read"),
        "note_append": Tool("note_append", "write"),
    },
    GATE=Gate(),
)
adapter = V2ToolAdapter(tools)


class Executor:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, step):
        self.calls.append((step.tool, dict(step.args)))
        return {"tool": step.tool, "call": len(self.calls)}


planner_calls = {"count": 0}


async def scripted_chat(messages, model):
    planner_calls["count"] += 1
    assert model == "local-replanner"
    prompt = messages[0]["content"]
    assert "fixed-write-payload" not in prompt
    return (
        '{"steps":[{"tool":"current_datetime","args":{}}],'
        '"rationale":"One fresh time read replaces the old model-list read"}'
    )


root = tempfile.mkdtemp(prefix="agent3-review-replan-api-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
review_store = ReadReviewStore(os.path.join(root, "reviews.db"))
executor = Executor()
orchestrator = ReviewingAgent3Orchestrator(
    run_store,
    executor,
    review_store,
    confirmation_ttl_seconds=60,
)
policy = ReadSuffixReplanner(max_steps=8, max_replans=3)
journal = ReplanJournal(os.path.join(root, "journal.db"))
persistent = PersistentReadReplanner(run_store, journal, policy)
preview_service = ReplanPreviewService(
    run_store,
    persistent,
    TypedReadReplanPlanner(adapter, policy, chat_fn=scripted_chat),
    PlanStore(os.path.join(root, "previews.db"), ttl_seconds=300),
)
caps = CapabilitySnapshot(
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
        capability_provider=lambda _req, _adapter: caps,
        validation_provider=lambda: {"eligible_for_developer_preview": False},
        worker_version="test",
        replan_service=persistent,
    allow_client_plans = True)
)
app.include_router(
    build_replan_preview_router(preview_service, review_store=review_store)
)
client = TestClient(app)


# Start executes one read and persists an exact review checkpoint.
started_response = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "review and replan",
        "mode": "rig",
        "tools": True,
        "review_reads": True,
        "plan": [
            {"tool": "rig_status", "args": {}},
            {"tool": "list_models", "args": {}},
            {"tool": "note_append", "args": {"text": "fixed-write-payload"}},
        ],
    },
)
assert started_response.status_code == 200, started_response.text
started = started_response.json()
run = started["run"]
run_id = run["id"]
old_read_id = run["steps"][1]["id"]
write_id = run["steps"][2]["id"]
assert run["state"] == "running"
assert run["current_step"] == 1
assert [step["state"] for step in run["steps"]] == ["succeeded", "pending", "pending"]
assert executor.calls == [("rig_status", {})]
assert started["read_review"]["enabled"] is True
assert started["read_review"]["waiting"] is True
assert started["read_review"]["removable_step_ids"] == [old_read_id]


# Preview is read-only and the model never sees immutable write arguments.
preview_response = client.post(
    f"/experimental/agent3/runs/{run_id}/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert preview_response.status_code == 200, preview_response.text
preview = preview_response.json()
assert preview["executed"] is False
assert preview["window"]["removable_step_ids"] == [old_read_id]
assert preview["window"]["immutable_tail_ids"] == [write_id]
assert preview["plan"][0]["tool"] == "current_datetime"
assert executor.calls == [("rig_status", {})]
assert planner_calls["count"] == 1
assert review_store.get(run_id)["removable_step_ids"] == [old_read_id]


# Apply consumes the reviewed token, preserves the write tail and rebinds the
# paused checkpoint to the newly persisted replacement read.
preview_id = preview["preview_id"]
apply_response = client.post(
    f"/experimental/agent3/replan-previews/{preview_id}/apply"
)
assert apply_response.status_code == 200, apply_response.text
applied = apply_response.json()
assert [step["tool"] for step in applied["run"]["steps"]] == [
    "rig_status",
    "current_datetime",
    "note_append",
]
new_read_id = applied["run"]["steps"][1]["id"]
assert new_read_id != old_read_id
assert applied["run"]["steps"][2]["id"] == write_id
assert applied["run"]["steps"][2]["args"] == {"text": "fixed-write-payload"}
assert applied["read_review"]["waiting"] is True
assert applied["read_review"]["removable_step_ids"] == [new_read_id]
assert old_read_id not in applied["read_review"]["removable_step_ids"]
assert executor.calls == [("rig_status", {})]
assert planner_calls["count"] == 1
assert client.post(
    f"/experimental/agent3/replan-previews/{preview_id}/apply"
).status_code == 409


# GET exposes the same authoritative checkpoint. Explicit resume runs only the
# replacement read and then reaches the untouched write confirmation.
loaded_response = client.get(f"/experimental/agent3/runs/{run_id}")
assert loaded_response.status_code == 200, loaded_response.text
loaded = loaded_response.json()
assert loaded["read_review"]["waiting"] is True
assert loaded["read_review"]["removable_step_ids"] == [new_read_id]

resume_response = client.post(f"/experimental/agent3/runs/{run_id}/resume")
assert resume_response.status_code == 200, resume_response.text
resumed = resume_response.json()
assert resumed["run"]["state"] == "waiting_confirmation"
assert resumed["run"]["current_step"] == 2
assert resumed["read_review"]["waiting"] is False
assert executor.calls == [("rig_status", {}), ("current_datetime", {})]
write = resumed["run"]["steps"][2]
assert write["id"] == write_id
assert write["state"] == "waiting_confirmation"
assert write["confirmation_digest"]


# The immutable write executes only after its own fresh confirmation.
confirm_response = client.post(
    f"/experimental/agent3/runs/{run_id}/confirm",
    json={
        "step_id": write_id,
        "decision": "approve",
        "digest": write["confirmation_digest"],
    },
)
assert confirm_response.status_code == 200, confirm_response.text
confirmed = confirm_response.json()
assert confirmed["run"]["state"] == "completed"
assert confirmed["read_review"]["waiting"] is False
assert executor.calls == [
    ("rig_status", {}),
    ("current_datetime", {}),
    ("note_append", {"text": "fixed-write-payload"}),
]

kinds = [
    event["kind"]
    for event in client.get(
        f"/experimental/agent3/runs/{run_id}/events"
    ).json()["events"]
]
for required in (
    "replan_review_required",
    "replan_committed",
    "replan_review_resumed",
    "confirmation_required",
    "confirmation_approved",
    "run_completed",
):
    assert required in kinds, (required, kinds)
assert kinds.index("replan_review_required") < kinds.index("replan_committed")
assert kinds.index("replan_committed") < kinds.index("replan_review_resumed")
assert kinds.index("replan_review_resumed") < kinds.index("confirmation_required")


# Retry is server-owned: a client cannot disable the original review policy or
# replace the stored plan. The retry pauses after its first cloned read.
retry_response = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "mutated client retry",
        "mode": "cloud",
        "tools": False,
        "review_reads": False,
        "retry_of_run_id": run_id,
        "plan": [{"tool": "note_append", "args": {"text": "malicious"}}],
    },
)
assert retry_response.status_code == 200, retry_response.text
retry = retry_response.json()
assert retry["read_review"]["enabled"] is True
assert retry["read_review"]["waiting"] is True
assert retry["run"]["request"]["message"] == "review and replan"
assert [step["tool"] for step in retry["run"]["steps"]] == [
    "rig_status",
    "current_datetime",
    "note_append",
]
assert executor.calls[-1] == ("rig_status", {})
assert ("note_append", {"text": "malicious"}) not in executor.calls

print("42 passed, 0 failed")
