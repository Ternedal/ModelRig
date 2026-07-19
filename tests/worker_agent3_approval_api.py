from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import (
    Agent3Orchestrator,
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

SECRET_TEXT = "agent3-api-approval-secret-minimum-32-bytes"
SECRET = SECRET_TEXT.encode()


class DummyAdapter:
    pass


def args_sha(args):
    raw = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def sign(run, *, revision=0, nonce_byte=b"x", changes=None):
    step = run.steps[run.current_step]
    now = int(time.time())
    claims = {
        "v": 1,
        "nonce": base64.urlsafe_b64encode(nonce_byte * 32).decode().rstrip("="),
        "device_id": "device-anders",
        "run_id": run.id,
        "step_id": step.id,
        "tool": step.tool,
        "args_sha256": args_sha(step.args),
        "confirmation_digest": step.confirmation_digest,
        "plan_revision": revision,
        "issued_at": now,
        "expires_at": min(now + 30, int(step.confirmation_expires_at)),
    }
    claims.update(changes or {})
    payload = json.dumps(claims, separators=(",", ":")).encode()
    payload_part = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(SECRET, payload_part.encode("ascii"), hashlib.sha256).digest()
    return payload_part + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def make_env(*, required=True):
    root = tempfile.mkdtemp(prefix="agent3-approval-api-")
    store = AgentRunStore(os.path.join(root, "runs.db"))
    executions = []

    def execute(step):
        executions.append((step.tool, dict(step.args)))
        return "appended"

    orchestrator = Agent3Orchestrator(store, execute)
    app = FastAPI()
    app.include_router(
        build_router(
            orchestrator,
            DummyAdapter(),
            approval_db_path=os.path.join(root, "approvals.db"),
            allow_client_plans=False,
        )
    )
    previous = {
        "KALIV_AGENT3_APPROVAL_REQUIRED": os.environ.get("KALIV_AGENT3_APPROVAL_REQUIRED"),
        "KALIV_AGENT3_APPROVAL_SECRET": os.environ.get("KALIV_AGENT3_APPROVAL_SECRET"),
    }
    os.environ["KALIV_AGENT3_APPROVAL_REQUIRED"] = "1" if required else "0"
    os.environ["KALIV_AGENT3_APPROVAL_SECRET"] = SECRET_TEXT
    return root, orchestrator, TestClient(app), executions, previous


def restore(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def seed(orchestrator, *, marker="MARKER", tool="note_append"):
    step = AgentStep(
        tool=tool,
        args={"text": marker},
        risk=RiskClass.WRITE,
        sensitivity=Sensitivity.PRIVATE,
        egress=EgressClass.LOCAL,
        state=StepState.WAITING_CONFIRMATION,
        summary="Append exact marker",
    )
    step.confirmation_digest = orchestrator._digest(step)
    step.confirmation_expires_at = time.time() + 60
    run = AgentRun(
        request=TurnRequest("append", mode="rig", tools=True),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[step],
        state=RunState.WAITING_CONFIRMATION,
    )
    orchestrator.store.save(run)
    return run


def post(client, run, *, approve, token=None, digest=None):
    payload = {
        "step_id": run.steps[0].id,
        "decision": "approve" if approve else "deny",
        "digest": digest or run.steps[0].confirmation_digest,
    }
    if token is not None:
        payload["approval_token"] = token
    return client.post(f"/experimental/agent3/runs/{run.id}/confirm", json=payload)


def test_required_approve_without_token_fails_before_execution() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator)
        response = post(client, run, approve=True)
        assert response.status_code == 409, response.text
        assert "backend-issued" in response.json()["detail"]
        assert executions == []
        assert orchestrator.store.load(run.id).state == RunState.WAITING_CONFIRMATION
    finally:
        restore(previous)


def test_deny_never_needs_or_consumes_approval() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator)
        response = post(client, run, approve=False)
        assert response.status_code == 200, response.text
        assert response.json()["run"]["state"] == "cancelled"
        assert response.json()["approval_receipt"] is None
        assert executions == []
        kinds = [event["kind"] for event in orchestrator.store.events(run.id)]
        assert kinds == ["confirmation_denied"]
    finally:
        restore(previous)


def test_valid_token_consumes_then_executes_once_with_redacted_receipt() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator)
        token = sign(run)
        response = post(client, run, approve=True, token=token)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run"]["state"] == "completed"
        assert executions == [("note_append", {"text": "MARKER"})]
        receipt = body["approval_receipt"]
        assert receipt["device_id"] == "device-anders"
        assert receipt["plan_revision"] == 0
        assert token not in json.dumps(receipt)
        events = orchestrator.store.events(run.id)
        kinds = [event["kind"] for event in events]
        assert kinds == [
            "approval_consumed",
            "confirmation_approved",
            "policy_decision",
            "step_started",
            "step_succeeded",
            "run_completed",
        ]
        encoded = json.dumps(events)
        assert token not in encoded
        assert base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=") not in encoded
    finally:
        restore(previous)


def test_changed_args_or_digest_fails_before_execution() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator)
        token = sign(run)
        stored = orchestrator.store.load(run.id)
        stored.steps[0].args = {"text": "CHANGED"}
        orchestrator.store.save(stored)
        response = post(client, run, approve=True, token=token)
        assert response.status_code == 409, response.text
        assert "no longer matches" in response.json()["detail"]
        assert executions == []

        run2 = seed(orchestrator, marker="SECOND")
        token2 = sign(run2, nonce_byte=b"y")
        response2 = post(client, run2, approve=True, token=token2, digest="f" * 64)
        assert response2.status_code == 409, response2.text
        assert executions == []
    finally:
        restore(previous)


def test_deny_with_token_is_rejected_without_execution() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator)
        response = post(client, run, approve=False, token=sign(run))
        assert response.status_code == 409, response.text
        assert "deny must not carry" in response.json()["detail"]
        assert executions == []
    finally:
        restore(previous)


def test_non_note_write_token_is_rejected() -> None:
    _, orchestrator, client, executions, previous = make_env(required=True)
    try:
        run = seed(orchestrator, tool="delete_model")
        response = post(client, run, approve=True, token=sign(run))
        assert response.status_code == 409, response.text
        assert "restricted to note_append" in response.json()["detail"]
        assert executions == []
    finally:
        restore(previous)


def test_legacy_dev_flow_remains_available_when_gate_is_off() -> None:
    _, orchestrator, client, executions, previous = make_env(required=False)
    try:
        os.environ.pop("KALIV_AGENT3_APPROVAL_SECRET", None)
        run = seed(orchestrator)
        response = post(client, run, approve=True)
        assert response.status_code == 200, response.text
        assert executions == [("note_append", {"text": "MARKER"})]
        assert response.json()["approval_receipt"] is None
    finally:
        restore(previous)


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"agent3 approval API: {len(TESTS)} passed")
