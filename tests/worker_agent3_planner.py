from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import CapabilitySnapshot, TurnRequest
from app.agent3.integration import Agent3PlanError, V2ToolAdapter
from app.agent3.planner import PlannerError, TypedPlanner, build_planner_router
from app.agent3.routing import StrictTurnRouter

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
    def __init__(self, name, risk, description="tool"):
        self.name = name
        self.risk = risk
        self.description = description
        self.params = {"type": "object", "properties": {}}

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
        "note_append": Tool("note_append", "write", "Skriv note"),
    },
    GATE=gate,
)
adapter = V2ToolAdapter(fake)


async def response(text):
    async def _chat(_messages, _model):
        return text

    return await TypedPlanner(adapter, chat_fn=_chat).plan("gør noget")


valid = asyncio.run(response('{"steps":[{"tool":"note_append","args":{"text":"hej"}}],"rationale":"gem noten"}'))
check(len(valid.calls) == 1 and valid.calls[0].tool == "note_append", "valid typed plan is parsed")

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
    asyncio.run(response('not json'))
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
