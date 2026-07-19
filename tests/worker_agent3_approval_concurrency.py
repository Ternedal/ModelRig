from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile

from app.agent3.approval import (
    Agent3ApprovalError,
    consume_agent3_approval,
    verify_agent3_approval,
)
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

SECRET = b"agent3-concurrency-secret-minimum-32-bytes"
NOW = 1_900_000_000

step = AgentStep(
    tool="note_append",
    args={"text": "ONE IMMUTABLE APPEND"},
    risk=RiskClass.WRITE,
    sensitivity=Sensitivity.PRIVATE,
    egress=EgressClass.LOCAL,
    state=StepState.WAITING_CONFIRMATION,
    summary="Append once",
)
step.confirmation_digest = "a" * 64
step.confirmation_expires_at = NOW + 120
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


def args_sha() -> str:
    raw = json.dumps(step.args, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def token(nonce_byte: bytes) -> str:
    claims = {
        "v": 1,
        "nonce": base64.urlsafe_b64encode(nonce_byte * 32).decode().rstrip("="),
        "device_id": "device-anders",
        "run_id": run.id,
        "step_id": step.id,
        "tool": step.tool,
        "args_sha256": args_sha(),
        "confirmation_digest": step.confirmation_digest,
        "plan_revision": 0,
        "issued_at": NOW,
        "expires_at": NOW + 60,
    }
    raw = json.dumps(claims, separators=(",", ":")).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


first = verify_agent3_approval(
    token(b"a"), run, plan_revision=0, now=NOW, secret_factory=lambda: SECRET
)
second = verify_agent3_approval(
    token(b"b"), run, plan_revision=0, now=NOW, secret_factory=lambda: SECRET
)
assert first.nonce_sha256 != second.nonce_sha256
assert first.action_sha256 == second.action_sha256

with tempfile.TemporaryDirectory() as temp:
    db = os.path.join(temp, "approvals.db")
    consume_agent3_approval(first, db_path=db, now=NOW)
    try:
        consume_agent3_approval(second, db_path=db, now=NOW + 0.01)
    except Agent3ApprovalError as exc:
        assert "immutable action was already used" in str(exc)
    else:
        raise AssertionError("two different tokens authorized the same immutable append")

print("agent3 approval concurrency: 1 passed")
