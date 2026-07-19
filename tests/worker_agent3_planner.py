from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import CapabilitySnapshot, TurnRequest
from app.agent3.integration import Agent3PlanError, V2ToolAdapter
from app.agent3.planner import PlannerError, TypedPlanner, build_planner_router
from app.agent3.routing import StrictTurnRouter
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
    # Every planner-facing double declares the same canonical static axes as a
    # production Tool. The catalog may expose only three of them, but it must
    # validate the whole descriptor before any metadata enters a model prompt.
    def __init__(self, name, risk, description="tool", sensitivity="operational"):
        self.name = name
        self.risk = risk
        self.impact = risk
        self.sensitivity = sensitivity
        self.description = description
        self.params = {"type": "object", "properties": {}}
        self.isolate = False
        self.env_allow = ()
        self.schedulable = True
        self.unschedulable_because = ""
        self.cancellation = "none"
        self.idempotent = risk == "read"
        self.network = "none"
        self.network_destinations = ()

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None

    def __init__(self):
        self.disabled = set()
        self.proposals = 0

    def is_enabled(self, name):
        return self.enabled and name not in self.disabled

    def propose(self, *args, **kwargs):
        self.proposals += 1
        raise AssertionError("plan preview must never execute a tool")


gate = Gate()
fake = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read", "Læs rigstatus"),
        "note_append": Tool("note_append", "write", "Skriv note", sensitivity="private"),
    },
    GATE=gate,
)
adapter = V2ToolAdapter(fake)

legacy_catalog = [
    {
        "name": tool.name,
        "description": tool.description,
        "params": tool.params,
    }
    for tool in fake.REGISTRY.values()
    if adapter.is_enabled(tool.name)
]
check(adapter.tool_catalog() == legacy_catalog, "canonical catalog preserves legacy payload and insertion order")
check(
    all(set(item) == {"name", "description", "params"} for item in adapter.tool_catalog()),
    "planner catalog exposes no policy axes",
)
gate.disabled.add("note_append")
check(
    adapter.tool_catalog() == legacy_catalog[:1],
    "canonical catalog preserves enabled-tool filtering",
)
gate.disabled.clear()

seen_messages: list[list[dict]] = []


async def response(text):
    async def _chat(messages, _model):
        seen_messages.append(messages)
        return text

    return await TypedPlanner(adapter, chat_fn=_chat).plan("gør noget")


valid = asyncio.run(response('{"steps":[{"tool":"note_append","args":{"text":"hej"}}],"rationale":"gem noten"}'))
check(len(valid.calls) == 1 and valid.calls[0].tool == "note_append", "valid typed plan is parsed")
encoded_catalog = seen_messages[-1][0]["content"].split("Tool catalog: ", 1)[1]
check(
    json.loads(encoded_catalog) == legacy_catalog,
    "model prompt receives the exact legacy catalog payload",
)
check(
    encoded_catalog == json.dumps(legacy_catalog, ensure_ascii=False, sort_keys=True),
    "catalog prompt serialization remains byte-identical",
)

fenced = asyncio.run(response('```json\n{"steps":[{"tool":"rig_status","args":{}}]}\n```'))
check(fenced.calls[0].tool == "rig_status", "a single JSON code fence is tolerated")

try:
    asyncio.run(response('{"steps":[{"tool":"note_append","args":{},"risk":"read"}]}'))
    injected = False
except PlannerError:
    injected = True
check(injected, "model-supplied risk field is rejected")

try:
    asyncio.run(response('{"steps":[],"approved":true}'))
    top_level = False
except PlannerError:
    top_level = True
check(top_level, "unsupported top-level approval field is rejected")

try:
    asyncio.run(response("not json"))
    malformed = False
except PlannerError:
    malformed = True
check(malformed, "malformed planner output is rejected")

unknown = asyncio.run(response('{"steps":[{"tool":"shell","args":{"cmd":"whoami"}}]}'))
route = StrictTurnRouter().route(
    TurnRequest("x", mode="rig", tools=True),
    CapabilitySnapshot(True, True, True, False, True, False),
)
try:
    adapter.build_steps(unknown.calls, route, None)
    unknown_blocked = False
except Agent3PlanError:
    unknown_blocked = True
check(unknown_blocked, "unknown tool is rejected by the registry adapter")

gate.disabled.add("note_append")
try:
    adapter.build_steps(valid.calls, route, None)
    disabled_blocked = False
except Agent3PlanError:
    disabled_blocked = True
check(disabled_blocked, "disabled tool is rejected after planning")
gate.disabled.clear()

bad = Tool("bad_tool", "read", "bad metadata")
bad.network = "vpn_magic"
bad_adapter = V2ToolAdapter(
    SimpleNamespace(REGISTRY={"bad_tool": bad}, GATE=Gate())
)
bad_chat_calls = 0


async def bad_chat(_messages, _model):
    global bad_chat_calls
    bad_chat_calls += 1
    return '{"steps":[]}'


try:
    asyncio.run(TypedPlanner(bad_adapter, chat_fn=bad_chat).plan("test"))
    invalid_descriptor_blocked = False
except Agent3PlanError:
    invalid_descriptor_blocked = True
check(invalid_descriptor_blocked, "invalid descriptor blocks planner catalog generation")
check(bad_chat_calls == 0, "invalid descriptor is rejected before the model is called")


async def api_chat(_messages, _model):
    return '{"steps":[{"tool":"note_append","args":{"text":"api"}}],"rationale":"preview"}'


app = FastAPI()
app.include_router(build_planner_router(adapter, TypedPlanner(adapter, chat_fn=api_chat)))
client = TestClient(app)
preview = client.post(
    "/experimental/agent3/plan",
    json={"message": "gem en note", "mode": "rig"},
)
body = preview.json()
check(preview.status_code == 200, "plan-preview endpoint accepts a valid local plan")
check(body["executed"] is False and gate.proposals == 0, "plan preview never executes tools")
check(body["plan"][0]["risk"] == "write", "risk is added from code, not model output")
check(body["plan"][0]["sensitivity"] == "private", "sensitivity is added from code")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
