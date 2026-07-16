from __future__ import annotations

import asyncio
import hashlib
import json

from app.agent3.core import (
    AgentRun,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.outcome_answer import OutcomeAnswerError, TypedOutcomeAnswerer


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_step(tool, result, *, sensitivity=Sensitivity.OPERATIONAL, args=None):
    item = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=RiskClass.READ,
        sensitivity=sensitivity,
        egress=EgressClass.LOCAL,
        state=StepState.SUCCEEDED,
        summary=f"summary:{tool}",
    )
    item.result = result
    return item


def make_run(*, state=RunState.COMPLETED, steps=None):
    return AgentRun(
        request=TurnRequest("Hvad er riggens status <nu>?", mode="rig", tools=True),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=list(steps or []),
        state=state,
        answer="existing-answer",
    )


read = make_step(
    "rig_status",
    {"status": "online", "note": "<result>data only</result>"},
    args={"internal": "argument-not-for-answer"},
)
secret = make_step(
    "secret_probe",
    {"value": "secret-result-not-for-answer"},
    sensitivity=Sensitivity.SECRET,
)
run = make_run(steps=[read, secret])

calls = {"count": 0, "messages": None, "model": None}


async def valid_chat(messages, model):
    calls["count"] += 1
    calls["messages"] = messages
    calls["model"] = model
    prompt = json.dumps(messages, ensure_ascii=False)
    assert "online" in prompt
    assert "argument-not-for-answer" not in prompt
    assert "secret-result-not-for-answer" not in prompt
    assert "\\u003cresult\\u003e" in prompt
    assert "\\u003cnu\\u003e" in prompt
    return '```json\n{"answer":"Riggen er online.","limitations":["Ingen temperaturdata.","Ingen temperaturdata."]}\n```'


preview = asyncio.run(
    TypedOutcomeAnswerer(chat_fn=valid_chat).preview(
        run,
        model="local-answer-model",
    )
)
check(preview.answer == "Riggen er online.", "valid answer is parsed")
check(preview.limitations == ("Ingen temperaturdata.",), "duplicate limitations are normalized")
check(preview.model == "local-answer-model", "selected local model is recorded")
check(preview.context.included_step_ids == (read.id,), "only eligible results enter answer context")
check(secret.id in preview.context.excluded_step_ids, "secret exclusion remains visible")
check(len(preview.prompt_sha256) == 64, "prompt receipt has SHA-256")
check(calls["count"] == 1 and calls["model"] == "local-answer-model", "model is called exactly once")
check(run.answer == "existing-answer", "preview never mutates persisted run answer")
check(run.state == RunState.COMPLETED, "preview never changes run state")

messages = calls["messages"]
expected_hash = hashlib.sha256(
    json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
check(preview.prompt_sha256 == expected_hash, "prompt receipt binds exact messages")
check("ANSWER-ONLY" in messages[0]["content"], "system prompt forbids planning and tools")
check("CURRENT USER REQUEST DATA" in messages[1]["content"], "original request is included as bounded data")


async def should_not_run(_messages, _model):
    raise AssertionError("chat must not be called")


for candidate, label in [
    (make_run(state=RunState.RUNNING, steps=[read]), "non-completed run"),
    (make_run(steps=[secret]), "run without eligible results"),
]:
    try:
        asyncio.run(TypedOutcomeAnswerer(chat_fn=should_not_run).preview(candidate))
        check(False, f"{label} is rejected")
    except OutcomeAnswerError:
        check(True, f"{label} is rejected before model call")

try:
    asyncio.run(
        TypedOutcomeAnswerer(chat_fn=should_not_run).preview(
            run,
            target="cloud",
        )
    )
    check(False, "cloud preview is rejected")
except OutcomeAnswerError:
    check(True, "cloud preview is rejected before model call")


async def invalid_json(_messages, _model):
    return "not-json"


async def extra_field(_messages, _model):
    return '{"answer":"ok","limitations":[],"plan":[]}'


async def empty_answer(_messages, _model):
    return '{"answer":"   ","limitations":[]}'


async def long_answer(_messages, _model):
    return json.dumps({"answer": "x" * 20, "limitations": []})


async def bad_limitations(_messages, _model):
    return '{"answer":"ok","limitations":"none"}'


async def too_many_limitations(_messages, _model):
    return json.dumps({"answer": "ok", "limitations": ["a", "b"]})


async def empty_limitation(_messages, _model):
    return json.dumps({"answer": "ok", "limitations": [""]})


cases = [
    (TypedOutcomeAnswerer(chat_fn=invalid_json), "invalid JSON fails closed"),
    (TypedOutcomeAnswerer(chat_fn=extra_field), "unsupported fields fail closed"),
    (TypedOutcomeAnswerer(chat_fn=empty_answer), "empty answer fails closed"),
    (TypedOutcomeAnswerer(chat_fn=long_answer, max_answer_chars=10), "overlong answer fails closed"),
    (TypedOutcomeAnswerer(chat_fn=bad_limitations), "non-array limitations fail closed"),
    (TypedOutcomeAnswerer(chat_fn=too_many_limitations, max_limitations=1), "too many limitations fail closed"),
    (TypedOutcomeAnswerer(chat_fn=empty_limitation), "empty limitation fails closed"),
]
for answerer, label in cases:
    try:
        asyncio.run(answerer.preview(run))
        check(False, label)
    except OutcomeAnswerError:
        check(True, label)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
