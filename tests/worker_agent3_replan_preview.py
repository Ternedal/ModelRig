from __future__ import annotations

import asyncio
import json
import os
import tempfile
from copy import deepcopy
from types import SimpleNamespace

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.replan_planner import TypedReadReplanPlanner
from app.agent3.replan_preview import ReplanPreviewError, ReplanPreviewService
from app.agent3.replan_runtime import PersistentReadReplanner, ReplanJournal, plan_digest
from app.agent3.replanner import ReadSuffixReplanner


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(fn, name):
    try:
        fn()
    except ReplanPreviewError:
        check(True, name)
    else:
        check(False, name)


class Tool:
    def __init__(self, name, risk):
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


def step(tool, risk=RiskClass.READ, *, state=StepState.PENDING, args=None):
    item = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="conv-1",
        summary=f"summary:{tool}",
        state=state,
    )
    return item


def make_run(label):
    done = step("rig_status", state=StepState.SUCCEEDED)
    done.result = {"status": "online"}
    return AgentRun(
        request=TurnRequest(label, mode="rig", tools=True, conversation_id="conv-1"),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[
            done,
            step("list_models"),
            step("current_datetime"),
            step(
                "note_append",
                RiskClass.WRITE,
                args={"text": f"IMMUTABLE_SECRET_WRITE_ARG_{label}"},
            ),
        ],
        current_step=1,
    )


model_calls = {"count": 0}


async def chat(_messages, _model):
    model_calls["count"] += 1
    return '{"steps":[{"tool":"rig_status","args":{"detail":true}}],"rationale":"Use one status read"}'


root = tempfile.mkdtemp(prefix="agent3-replan-preview-")
store = AgentRunStore(os.path.join(root, "runs.db"))
journal = ReplanJournal(os.path.join(root, "journal.db"))
policy = ReadSuffixReplanner(max_steps=8, max_replans=3)
persistent = PersistentReadReplanner(store, journal, policy)
preview_store = PlanStore(os.path.join(root, "previews.db"), ttl_seconds=300)
planner = TypedReadReplanPlanner(adapter, policy, chat_fn=chat)
service = ReplanPreviewService(store, persistent, planner, preview_store)

# Reviewed preview is side-effect free and stores no immutable write args.
run = make_run("normal")
store.save(run)
before = plan_digest(run)
preview_id, ttl, stored, proposal = asyncio.run(
    service.preview(run.id, model="local-test")
)
check(bool(preview_id) and ttl == 300, "preview returns a short-lived token")
check(plan_digest(store.load(run.id)) == before, "preview does not mutate the run")
check(journal.history(run.id) == [], "preview does not reserve a replan transaction")
check(stored.before_digest == before and stored.revision == 0, "preview binds run digest and revision")
check(stored.removable_step_ids == tuple(item.id for item in run.steps[1:3]), "preview binds removable step ids")
check([item.tool for item in proposal.steps] == ["rig_status"], "preview retains registry-classified replacement")
raw_payload = preview_store._conn.execute(
    "SELECT payload FROM agent_plans WHERE id=?", (preview_id,)
).fetchone()[0]
check("IMMUTABLE_SECRET_WRITE_ARG_normal" not in raw_payload, "stored preview excludes immutable write args")
check(model_calls["count"] == 1, "preview calls the model once")

revised, receipt, applied = service.apply(preview_id)
check([item.tool for item in revised.steps] == ["rig_status", "rig_status", "note_append"], "single-use preview applies exact replacement")
check(revised.steps[-1].args == {"text": "IMMUTABLE_SECRET_WRITE_ARG_normal"}, "apply preserves immutable write tail")
check(receipt["removed_step_ids"] == list(applied.removable_step_ids), "committed receipt matches reviewed window")
check(journal.revision_state(run.id) == (1, 1), "applied preview creates one committed revision")
check(model_calls["count"] == 1, "apply does not call the model again")
expect_error(lambda: service.apply(preview_id), "preview token is single-use")

# Any persisted run change consumes and invalidates the reviewed token.
stale_run = make_run("stale")
store.save(stale_run)
stale_id, _, _, _ = asyncio.run(service.preview(stale_run.id))
changed = store.load(stale_run.id)
changed.steps[1].args["changed"] = True
store.save(changed)
expect_error(lambda: service.apply(stale_id), "changed run makes preview stale")
expect_error(lambda: service.apply(stale_id), "stale token remains consumed")

# A separately committed revision invalidates an older preview even when a new
# plan could otherwise look structurally similar.
revision_run = make_run("revision")
store.save(revision_run)
revision_preview_id, _, _, _ = asyncio.run(service.preview(revision_run.id))
persistent.apply(
    revision_run.id,
    [step("rig_status")],
    reason="operator committed a different revision",
)
expect_error(
    lambda: service.apply(revision_preview_id),
    "changed journal revision invalidates reviewed preview",
)

# Tampering the stored replacement into a write cannot bypass policy.
tamper_run = make_run("tamper")
store.save(tamper_run)
tamper_id, _, _, _ = asyncio.run(service.preview(tamper_run.id))
row = preview_store._conn.execute(
    "SELECT payload FROM agent_plans WHERE id=?", (tamper_id,)
).fetchone()
payload = json.loads(row[0])
payload["steps"][0]["tool"] = "note_append"
payload["steps"][0]["args"] = {"text": "bad"}
payload["steps"][0]["risk"] = "write"
preview_store._conn.execute(
    "UPDATE agent_plans SET payload=? WHERE id=?",
    (json.dumps(payload), tamper_id),
)
preview_store._conn.commit()
expect_error(lambda: service.apply(tamper_id), "tampered stored write is rejected")
check(journal.history(tamper_run.id) == [], "tampered token never reaches replan journal")

# Empty read proposal is also reviewable and can remove redundant work.
async def empty_chat(_messages, _model):
    return '{"steps":[],"rationale":"No more reads are needed"}'


empty_run = make_run("empty")
store.save(empty_run)
empty_service = ReplanPreviewService(
    store,
    persistent,
    TypedReadReplanPlanner(adapter, policy, chat_fn=empty_chat),
    preview_store,
)
empty_id, _, _, empty_proposal = asyncio.run(empty_service.preview(empty_run.id))
check(empty_proposal.steps == [], "empty LLM proposal can be reviewed")
empty_revised, _, _ = empty_service.apply(empty_id)
check([item.tool for item in empty_revised.steps] == ["rig_status", "note_append"], "empty proposal removes only pending reads")

# Recovery conflict blocks preview before the model is called.
conflict_run = make_run("conflict")
store.save(conflict_run)
expected = deepcopy(conflict_run)
conflict_receipt = policy.apply(
    expected,
    [step("rig_status")],
    reason="expected",
    revision=0,
    replan_count=0,
)
journal.prepare(
    conflict_run.id,
    conflict_receipt,
    before_digest=plan_digest(conflict_run),
    after_digest=plan_digest(expected),
)
third = deepcopy(conflict_run)
third.steps[1:3] = [step("list_models", args={"third": True})]
store.save(third)
calls_before = model_calls["count"]
expect_error(
    lambda: asyncio.run(service.preview(conflict_run.id)),
    "recovery conflict blocks model preview",
)
check(model_calls["count"] == calls_before, "conflict is detected before model call")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
