from __future__ import annotations

import hashlib
import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.memory import MemoryStore
from helpers.memory_protector import TestMemoryProtector
from app.agent3.plan_store import PlanStore
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
        raise AssertionError("write must wait for Agent 3.0 confirmation")


fake = SimpleNamespace(REGISTRY={"note_append": Tool()}, GATE=Gate())
adapter = V2ToolAdapter(fake)
seen_messages: list[list[dict]] = []


async def planned(messages, _model):
    seen_messages.append(messages)
    return '{"steps":[{"tool":"note_append","args":{"text":"planned"}}],"rationale":"test"}'


root = tempfile.mkdtemp(prefix="agent3-planner-memory-")
memory_store = MemoryStore(
    os.path.join(root, "memory.db"),
    protector=TestMemoryProtector(),
)
public = memory_store.create(
    subject="modelrig",
    predicate="gpu",
    value="RTX 3060 12GB",
    sensitivity="public",
)
operational = memory_store.create(
    subject="modelrig",
    predicate="os",
    value="Windows 11",
    sensitivity="operational",
)
private = memory_store.create(
    subject="anders",
    predicate="food",
    value="ingen fisk",
    kind="preference",
    sensitivity="private",
)
secret = memory_store.create(
    subject="anders",
    predicate="token",
    value="never-send-this",
    sensitivity="secret",
)
pending = memory_store.create(
    subject="anders",
    predicate="possible_model",
    value="qwen",
    sensitivity="operational",
    source_type="inferred",
)

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
        memory_store=memory_store,
    )
)
client = TestClient(app)

plain = client.post("/experimental/agent3/plan", json={"message": "gem status"})
plain_body = plain.json()
check(plain.status_code == 200, "ordinary planning still succeeds")
check(plain_body["memory_context"]["requested"] is False, "memory is opt-in by default")
check(plain_body["memory_context"]["sent_to_model"] is False, "default planning sends no memory")
check("KALIV MEMORY DATA" not in seen_messages[-1][-1]["content"], "default model prompt contains no memory block")

local = client.post(
    "/experimental/agent3/plan",
    json={"message": "gem status", "use_memory": True, "memory_max_chars": 12000},
)
local_body = local.json()
local_receipt = local_body["memory_context"]
local_user = seen_messages[-1][-1]["content"]
local_context = local_user.split("\n\n----- BEGIN CURRENT USER REQUEST -----", 1)[0]
check(local.status_code == 200 and local_receipt["requested"] is True, "explicit local memory planning succeeds")
check(local_receipt["sent_to_model"] is True and local_receipt["target"] == "local", "local receipt reports actual model use")
check(public.id in local_receipt["included_ids"] and private.id in local_receipt["included_ids"], "local planning may use confirmed public and private memory")
check(secret.id not in local_receipt["included_ids"] and pending.id not in local_receipt["included_ids"], "secret and pending memory never enter the planner")
check("never-send-this" not in local_user and "possible_model" not in local_user, "blocked memory values are absent from the model prompt")
check(
    local_receipt["sha256"] == hashlib.sha256(local_context.encode("utf-8")).hexdigest(),
    "receipt SHA matches the exact memory block sent to the planner",
)
check(local_receipt["character_count"] == len(local_context), "receipt character count matches the exact block")

plan_id = local_body["plan_id"]
started = client.post(f"/experimental/agent3/plans/{plan_id}/start")
check(started.status_code == 200, "memory-backed reviewed plan starts")
check(started.json()["memory_context"] == local_receipt, "single-use plan preserves the reviewed memory receipt")
check(started.json()["run"]["state"] == "waiting_confirmation", "memory does not bypass write confirmation")

cloud = client.post(
    "/experimental/agent3/plan",
    json={
        "message": "gem status",
        "mode": "cloud",
        "cloud_ready": True,
        "use_memory": True,
        "memory_max_chars": 12000,
    },
)
cloud_receipt = cloud.json()["memory_context"]
check(cloud.status_code == 200 and cloud_receipt["target"] == "cloud", "cloud route selects cloud memory policy")
check(public.id in cloud_receipt["included_ids"] and operational.id in cloud_receipt["included_ids"], "public and operational memory may reach cloud planning")
check(private.id not in cloud_receipt["included_ids"] and private.id in cloud_receipt["excluded_ids"], "private memory is excluded from cloud without consent")
check("ingen fisk" not in seen_messages[-1][-1]["content"], "private value is absent from cloud planner prompt without consent")

cloud_private = client.post(
    "/experimental/agent3/plan",
    json={
        "message": "gem status",
        "mode": "cloud",
        "cloud_ready": True,
        "use_memory": True,
        "allow_private_cloud": True,
        "memory_max_chars": 12000,
    },
)
cloud_private_receipt = cloud_private.json()["memory_context"]
check(private.id in cloud_private_receipt["included_ids"], "explicit private-cloud consent allows private memory")
check(secret.id not in cloud_private_receipt["included_ids"], "secret remains blocked despite private-cloud consent")

filtered = client.post(
    "/experimental/agent3/plan",
    json={
        "message": "gem status",
        "use_memory": True,
        "memory_subjects": ["modelrig"],
        "memory_max_chars": 12000,
    },
)
filtered_ids = set(filtered.json()["memory_context"]["included_ids"])
check(filtered_ids == {public.id, operational.id}, "subject filter is server-applied before planning")

zero_budget = client.post(
    "/experimental/agent3/plan",
    json={"message": "gem status", "use_memory": True, "memory_max_chars": 0},
)
zero_receipt = zero_budget.json()["memory_context"]
check(zero_receipt["requested"] is True and zero_receipt["sent_to_model"] is False, "zero budget records opt-in without sending memory")
check("KALIV MEMORY DATA" not in seen_messages[-1][-1]["content"], "zero budget adds no decorative memory block")

missing_calls = 0


async def should_not_plan(_messages, _model):
    global missing_calls
    missing_calls += 1
    return '{"steps":[]}'


missing_app = FastAPI()
missing_app.include_router(build_planner_router(adapter, TypedPlanner(adapter, chat_fn=should_not_plan)))
missing = TestClient(missing_app).post(
    "/experimental/agent3/plan",
    json={"message": "gem status", "use_memory": True},
)
check(missing.status_code == 409, "memory opt-in fails closed when the store is not mounted")
check(missing_calls == 0, "planner is not called when requested memory cannot be supplied")

memory_store.close()
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
