from __future__ import annotations

import json
import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
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
from app.agent3.outcome_answer import TypedOutcomeAnswerer
from app.agent3.outcome_answer_api import build_outcome_answer_router


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
        request=TurnRequest("Er riggen klar?", mode="rig", tools=True),
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
        answer="stored-answer-before-preview",
    )


root = tempfile.mkdtemp(prefix="agent3-outcome-answer-api-")
store = AgentRunStore(os.path.join(root, "runs.db"))
read = make_step(
    "rig_status",
    {"status": "online", "detail": "worker ready"},
    args={"internal_arg": "must-not-reach-model"},
)
secret = make_step(
    "secret_probe",
    {"token": "must-not-reach-model"},
    sensitivity=Sensitivity.SECRET,
)
completed = make_run(steps=[read, secret])
store.save(completed)

calls = {"count": 0}


async def scripted_chat(messages, model):
    calls["count"] += 1
    assert model == "local-answer-model"
    prompt = json.dumps(messages, ensure_ascii=False)
    assert "worker ready" in prompt
    assert "internal_arg" not in prompt
    assert "must-not-reach-model" not in prompt
    return '{"answer":"Ja, riggen er online og workeren er klar.","limitations":[]}'


app = FastAPI()
app.include_router(
    build_outcome_answer_router(
        store,
        TypedOutcomeAnswerer(chat_fn=scripted_chat),
    )
)
client = TestClient(app)

response = client.post(
    f"/experimental/agent3/runs/{completed.id}/answer-preview",
    json={"answer_model": "local-answer-model"},
)
assert response.status_code == 200, response.text
payload = response.json()
assert payload["run_id"] == completed.id
assert payload["run_state"] == "completed"
assert payload["answer"] == "Ja, riggen er online og workeren er klar."
assert payload["limitations"] == []
assert payload["answer_model"] == "local-answer-model"
assert payload["context"]["target"] == "local"
assert payload["context"]["included_step_ids"] == [read.id]
assert payload["context"]["excluded_step_ids"] == [secret.id]
assert len(payload["context"]["sha256"]) == 64
assert len(payload["prompt_sha256"]) == 64
assert payload["executed"] is False
assert payload["persisted"] is False
assert payload["delivered_to_chat"] is False
assert calls["count"] == 1
reloaded = store.load(completed.id)
assert reloaded.answer == "stored-answer-before-preview"
assert reloaded.state == RunState.COMPLETED

missing = client.post(
    "/experimental/agent3/runs/does-not-exist/answer-preview",
    json={},
)
assert missing.status_code == 404, missing.text

running = make_run(state=RunState.RUNNING, steps=[read])
store.save(running)
running_response = client.post(
    f"/experimental/agent3/runs/{running.id}/answer-preview",
    json={},
)
assert running_response.status_code == 409, running_response.text
assert "completed" in running_response.json()["detail"]
assert calls["count"] == 1

secret_only = make_run(steps=[secret])
store.save(secret_only)
secret_response = client.post(
    f"/experimental/agent3/runs/{secret_only.id}/answer-preview",
    json={},
)
assert secret_response.status_code == 409, secret_response.text
assert "eligible" in secret_response.json()["detail"]
assert calls["count"] == 1

zero_budget = client.post(
    f"/experimental/agent3/runs/{completed.id}/answer-preview",
    json={"max_context_chars": 0},
)
assert zero_budget.status_code == 409, zero_budget.text
assert calls["count"] == 1

invalid_bounds = client.post(
    f"/experimental/agent3/runs/{completed.id}/answer-preview",
    json={"max_context_steps": 201},
)
assert invalid_bounds.status_code == 422, invalid_bounds.text
assert calls["count"] == 1

print("27 passed, 0 failed")
