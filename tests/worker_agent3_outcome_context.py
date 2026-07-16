from __future__ import annotations

import hashlib
import json

from app.agent3.core import (
    AgentRun,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.outcome_context import OutcomeContextCompiler, OutcomeTarget


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_step(
    tool,
    result,
    *,
    state=StepState.SUCCEEDED,
    sensitivity=Sensitivity.OPERATIONAL,
    risk=RiskClass.READ,
    args=None,
):
    item = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=sensitivity,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="internal-conversation-id",
        summary=f"summary <{tool}>",
        state=state,
    )
    item.result = result
    item.confirmation_digest = "internal-confirmation-value"
    return item


read_step = make_step(
    "rig_status",
    {"status": "online", "text": "<data>&value</data>"},
    args={"internal_arg": "not-for-context"},
)
private_step = make_step(
    "note_append",
    {"accepted": True, "payload": b"raw-bytes"},
    sensitivity=Sensitivity.PRIVATE,
    risk=RiskClass.WRITE,
    args={"text": "private-write-argument"},
)
secret_step = make_step(
    "secret_probe",
    {"value": "private-result-value"},
    sensitivity=Sensitivity.SECRET,
)
pending_step = make_step("pending", {"value": "pending-value"}, state=StepState.PENDING)
failed_step = make_step("failed", {"value": "failed-value"}, state=StepState.FAILED)

run = AgentRun(
    request=TurnRequest("summarize", mode="rig", tools=True),
    route=RoutePlan(
        RouteKind.RIG_TOOLS_LOCAL,
        "test",
        uses_cloud=False,
        uses_rig=True,
        uses_tools=True,
        uses_rag=False,
    ),
    steps=[read_step, private_step, secret_step, pending_step, failed_step],
)

compiler = OutcomeContextCompiler(max_string_chars=500)
local = compiler.compile(run, target=OutcomeTarget.LOCAL, max_chars=12_000)
check(local.included_step_ids == (read_step.id, private_step.id), "local includes successful non-secret results")
check(set(local.excluded_step_ids) == {secret_step.id, pending_step.id, failed_step.id}, "ineligible steps are listed as excluded")
check(local.character_count == len(local.text), "receipt reports exact character count")
check(local.sha256 == hashlib.sha256(local.text.encode()).hexdigest(), "receipt SHA binds the exact block")
check("kaliv-agent-outcome-context/v1" in local.text, "versioned schema is present")
check("untrusted tool output data" in local.text, "result block is explicitly inert")
check("\\u003cdata\\u003e" in local.text and "\\u0026" in local.text, "markup-looking values are escaped")
check("not-for-context" not in local.text, "read arguments are excluded")
check("private-write-argument" not in local.text, "write arguments are excluded")
check("internal-confirmation-value" not in local.text, "confirmation data is excluded")
check("internal-conversation-id" not in local.text, "conversation binding is excluded")
check("private-result-value" not in local.text, "secret result is excluded")
check("pending-value" not in local.text and "failed-value" not in local.text, "non-success results are excluded")
check('"binary_type":"bytes"' in local.text and "raw-bytes" not in local.text, "binary result bodies become metadata")

cloud = compiler.compile(run, target="cloud", max_chars=12_000)
check(cloud.included_step_ids == (read_step.id,), "cloud excludes private results without consent")
check(private_step.id in cloud.excluded_step_ids, "private cloud exclusion appears in receipt")
cloud_private = compiler.compile(
    run,
    target="cloud",
    allow_private_cloud=True,
    max_chars=12_000,
)
check(cloud_private.included_step_ids == (read_step.id, private_step.id), "explicit consent allows private cloud results")

zero = compiler.compile(run, max_chars=0)
check(zero.text == "" and zero.sha256 is None and zero.included_step_ids == (), "zero budget emits no block")

large = make_step("large", {"blob": "x" * 30_000})
small = make_step("small", {"ok": True})
budgeted = compiler.compile([large, small], max_chars=2_000)
check(budgeted.included_step_ids == (small.id,), "oversize result does not starve a later small result")
check(large.id in budgeted.excluded_step_ids, "oversize result is listed as excluded")

limited = compiler.compile([read_step, private_step], max_chars=12_000, max_steps=1)
check(limited.included_step_ids == (read_step.id,) and private_step.id in limited.excluded_step_ids, "step count budget is hard")

duplicate = compiler.compile([read_step, read_step], max_chars=12_000)
check(duplicate.included_step_ids == (read_step.id,), "duplicate ids are deduplicated")

again = compiler.compile(run, target=OutcomeTarget.LOCAL, max_chars=12_000)
check(again.text == local.text and again.sha256 == local.sha256, "compilation is deterministic")

payload = local.text.split("\n", 1)[1].rsplit("\n", 1)[0]
parsed = json.loads(payload)
check(parsed["schema"] == "kaliv-agent-outcome-context/v1" and len(parsed["items"]) == 2, "inner payload is valid JSON")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
