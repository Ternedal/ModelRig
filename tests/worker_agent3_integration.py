from __future__ import annotations

import os
import tempfile
import time
from types import SimpleNamespace

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
_tmp = tempfile.mkdtemp(prefix="kaliv-agent3-")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
os.environ["KALIV_TOOLS_STATE"] = os.path.join(_tmp, "tools-state.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "tools")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import (
    Agent3Orchestrator,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    ConfirmationError,
    RiskClass,
    RouteKind,
    RunState,
    StepState,
    TurnRequest,
    TurnRouter,
)
from app.agent3.integration import PlannedToolCall, V2ToolAdapter

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


caps = CapabilitySnapshot(True, True, True, True, True, True)
router = TurnRouter()
retry = router.route(
    TurnRequest(
        "igen",
        mode="cloud",
        tools=True,
        retry_of_run_id="run-1",
        original_route=RouteKind.RIG_TOOLS_CLOUD,
    ),
    caps,
)
check(retry.kind == RouteKind.RIG_TOOLS_CLOUD and retry.uses_tools, "retry preserves tools route")
retry_down = router.route(
    TurnRequest(
        "igen",
        mode="cloud",
        tools=True,
        retry_of_run_id="run-1",
        original_route=RouteKind.RIG_TOOLS_CLOUD,
    ),
    CapabilitySnapshot(cloud_ready=True),
)
check(retry_down.kind == RouteKind.UNAVAILABLE, "retry never silently downgrades an unavailable route")
check(
    router.route(TurnRequest("rag", mode="cloud", rag=True), caps).kind == RouteKind.UNAVAILABLE,
    "cloud RAG requires consent",
)


class FakeTool:
    def __init__(self, name, risk):
        self.name = name
        self.risk = risk

    def human_summary(self, args):
        return f"{self.name}: {args}"


class FakeGate:
    def __init__(self):
        self.enabled = True
        self.state_error = None
        self.pending = {}
        self.executed = []
        self.n = 0

    def propose(self, name, args, conversation_id=None, origin="local"):
        tool = fake_tools.REGISTRY[name]
        if tool.risk == "read":
            self.executed.append((name, dict(args), origin))
            return {"status": "executed", "result": f"read:{name}"}
        self.n += 1
        cid = f"c{self.n}"
        self.pending[cid] = (name, dict(args), origin)
        return {"status": "confirmation_required", "confirmation_id": cid}

    def confirm(self, cid, decision):
        name, args, origin = self.pending.pop(cid)
        if decision != "approve":
            return {"status": "denied", "tool": name}
        self.executed.append((name, args, origin))
        return {"status": "executed", "result": f"write:{name}"}


fake_gate = FakeGate()
fake_tools = SimpleNamespace(
    REGISTRY={
        "rig_status": FakeTool("rig_status", "read"),
        "list_documents": FakeTool("list_documents", "read"),
        "note_append": FakeTool("note_append", "write"),
        "delete_model": FakeTool("delete_model", "write"),
    },
    GATE=fake_gate,
)
adapter = V2ToolAdapter(fake_tools)
store = AgentRunStore(os.path.join(_tmp, "agent3.db"))
orch = Agent3Orchestrator(store=store, executor=adapter.execute, confirmation_ttl_seconds=5)

route = router.route(TurnRequest("gem", mode="rig", tools=True), caps)
steps = adapter.build_steps(
    [PlannedToolCall("note_append", {"text": "en"}), PlannedToolCall("note_append", {"text": "to"})],
    route,
    "conv-1",
)
run = orch.start_with_steps(TurnRequest("gem", mode="rig", tools=True), caps, steps)
check(run.state == RunState.WAITING_CONFIRMATION, "first write waits for confirmation")
first = run.steps[0]
run = orch.confirm(run.id, first.id, "approve", first.confirmation_digest)
check(run.state == RunState.WAITING_CONFIRMATION and run.current_step == 1, "second write gets a separate confirmation")
second = run.steps[1]
run = orch.confirm(run.id, second.id, "approve", second.confirmation_digest)
check(run.state == RunState.COMPLETED, "approved write chain completes")
check([x[0] for x in fake_gate.executed[-2:]] == ["note_append", "note_append"], "writes still execute through the V2 gate")

mut_steps = adapter.build_steps([PlannedToolCall("note_append", {"text": "original"})], route, "conv-2")
mut = orch.start_with_steps(TurnRequest("gem", mode="rig", tools=True), caps, mut_steps)
step = mut.steps[0]
digest = step.confirmation_digest
step.args["text"] = "changed"
store.save(mut)
try:
    orch.confirm(mut.id, step.id, "approve", digest)
    immutable = False
except ConfirmationError:
    immutable = True
check(immutable, "changed confirmation payload is rejected")

private_route = router.route(TurnRequest("docs", mode="cloud", tools=True), caps)
private_steps = adapter.build_steps([PlannedToolCall("list_documents", {})], private_route, "conv-3")
private = orch.start_with_steps(TurnRequest("docs", mode="cloud", tools=True), caps, private_steps)
check(private.state == RunState.BLOCKED, "private read output cannot reach cloud without consent")
private_ok = orch.start_with_steps(
    TurnRequest("docs", mode="cloud", tools=True),
    caps,
    adapter.build_steps([PlannedToolCall("list_documents", {})], private_route, "conv-4"),
    allow_private_cloud=True,
)
check(
    private_ok.state == RunState.WAITING_CONFIRMATION,
    "private-cloud consent still requires a concrete tool confirmation",
)
private_step = private_ok.steps[0]
private_ok = orch.confirm(private_ok.id, private_step.id, "approve", private_step.confirmation_digest)
check(private_ok.state == RunState.COMPLETED, "approved private cloud read completes")

proactive = orch.start_with_steps(
    TurnRequest("proaktiv", mode="rig", tools=True),
    caps,
    adapter.build_steps([PlannedToolCall("note_append", {"text": "x"})], route, "conv-5"),
    proactive=True,
)
check(proactive.state == RunState.BLOCKED, "proactive write is blocked")

# Crash-recovery invariant: an EXECUTING side effect is never replayed blindly.
crash_step = AgentStep("note_append", {"text": "x"}, RiskClass.WRITE, state=StepState.EXECUTING)
crash_run = orch.start_with_steps(TurnRequest("x", mode="rig", tools=True), caps, [])
crash_run.steps = [crash_step]
crash_run.current_step = 0
crash_run.state = RunState.RUNNING
store.save(crash_run)
crash = orch.advance(crash_run.id)
check(crash.state == RunState.BLOCKED and crash.steps[0].state == StepState.BLOCKED, "interrupted execution fails closed")

# API substrate: explicit plan only, no hidden LLM planner.
app = FastAPI()
app.include_router(build_router(orch, adapter, lambda req, _adapter: caps))
client = TestClient(app)
check(client.get("/experimental/agent3/status").status_code == 200, "experimental status endpoint is mounted")
check(client.post("/experimental/agent3/runs", json={"message": "hej", "tools": True}).status_code == 422, "empty implicit plan is refused")
resp = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "status",
        "mode": "rig",
        "tools": True,
        "plan": [{"tool": "rig_status", "args": {}}],
    },
)
check(resp.status_code == 200 and resp.json()["run"]["state"] == "completed", "API executes a validated read plan")
run_id = resp.json()["run"]["id"]
check(client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"], "run events are persisted and exposed")

# TTL: make a separate orchestrator with the smallest accepted TTL and force expiry.
expiry_store = AgentRunStore(os.path.join(_tmp, "expiry.db"))
expiry_orch = Agent3Orchestrator(expiry_store, adapter.execute, confirmation_ttl_seconds=5)
expiry = expiry_orch.start_with_steps(
    TurnRequest("gem", mode="rig", tools=True),
    caps,
    adapter.build_steps([PlannedToolCall("note_append", {"text": "ttl"})], route, "conv-ttl"),
)
expiry.steps[0].confirmation_expires_at = time.time() - 1
expiry_store.save(expiry)
try:
    expiry_orch.confirm(expiry.id, expiry.steps[0].id, "approve", expiry.steps[0].confirmation_digest)
    expired = False
except ConfirmationError:
    expired = True
check(expired and expiry_store.load(expiry.id).state == RunState.CANCELLED, "expired confirmation is a denial")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
