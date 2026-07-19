from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import replace

from app.agent3.approval import (
    Agent3ApprovalError,
    approval_required,
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

SECRET = b"agent3-approval-test-secret-32-bytes-minimum"
NOW = 1_900_000_000


def waiting_run(*, tool="note_append", args=None, revision=3):
    step = AgentStep(
        tool=tool,
        args={"text": "KALIV_WRITE_PILOT_MARKER"} if args is None else args,
        risk=RiskClass.WRITE,
        sensitivity=Sensitivity.PRIVATE,
        egress=EgressClass.LOCAL,
        state=StepState.WAITING_CONFIRMATION,
        summary="Append one bounded validation marker",
    )
    step.confirmation_digest = "a" * 64
    step.confirmation_expires_at = NOW + 120
    run = AgentRun(
        request=TurnRequest("append marker", mode="rig", tools=True),
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
    return run, revision


def args_sha(args):
    raw = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def token_for(run, revision, **changes):
    step = run.steps[run.current_step]
    claims = {
        "v": 1,
        "nonce": base64.urlsafe_b64encode(b"n" * 32).decode().rstrip("="),
        "device_id": "device-anders",
        "run_id": run.id,
        "step_id": step.id,
        "tool": step.tool,
        "args_sha256": args_sha(step.args),
        "confirmation_digest": step.confirmation_digest,
        "plan_revision": revision,
        "issued_at": NOW,
        "expires_at": NOW + 60,
    }
    claims.update(changes)
    payload = json.dumps(claims, separators=(",", ":")).encode()
    payload_part = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(SECRET, payload_part.encode("ascii"), hashlib.sha256).digest()
    signature_part = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return payload_part + "." + signature_part


def rejects(fn, contains):
    try:
        fn()
    except Agent3ApprovalError as exc:
        assert contains in str(exc), str(exc)
    else:
        raise AssertionError(f"expected Agent3ApprovalError containing {contains!r}")


def test_valid_token_binds_device_action_revision_and_time() -> None:
    run, revision = waiting_run()
    token = token_for(run, revision)
    approval = verify_agent3_approval(
        token,
        run,
        plan_revision=revision,
        now=NOW + 1,
        secret_factory=lambda: SECRET,
    )
    assert approval.device_id == "device-anders"
    assert approval.run_id == run.id
    assert approval.step_id == run.steps[0].id
    assert approval.tool == "note_append"
    assert approval.args_sha256 == args_sha(run.steps[0].args)
    assert approval.plan_revision == revision
    audit = approval.audit_payload()
    assert token not in json.dumps(audit)
    assert "n" * 32 not in json.dumps(audit)
    assert len(audit["approval_nonce_sha256"]) == 64
    assert len(audit["approval_token_sha256"]) == 64


def test_changed_args_digest_revision_and_run_fail_closed() -> None:
    run, revision = waiting_run()
    original = token_for(run, revision)
    run.steps[0].args = {"text": "CHANGED"}
    rejects(
        lambda: verify_agent3_approval(
            original, run, plan_revision=revision, now=NOW + 1, secret_factory=lambda: SECRET
        ),
        "no longer matches",
    )

    run, revision = waiting_run()
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, confirmation_digest="b" * 64),
            run,
            plan_revision=revision,
            now=NOW + 1,
            secret_factory=lambda: SECRET,
        ),
        "no longer matches",
    )
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision),
            run,
            plan_revision=revision + 1,
            now=NOW + 1,
            secret_factory=lambda: SECRET,
        ),
        "no longer matches",
    )
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, run_id="other-run"),
            run,
            plan_revision=revision,
            now=NOW + 1,
            secret_factory=lambda: SECRET,
        ),
        "no longer matches",
    )


def test_expired_future_and_overlong_tokens_fail_closed() -> None:
    run, revision = waiting_run()
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, expires_at=NOW),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "expired",
    )
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, issued_at=NOW + 40, expires_at=NOW + 50),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "not valid yet",
    )
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, expires_at=NOW + 181),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "lifetime",
    )


def test_token_cannot_outlive_confirmation() -> None:
    run, revision = waiting_run()
    run.steps[0].confirmation_expires_at = NOW + 30
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision, expires_at=NOW + 60),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "outlives",
    )


def test_only_note_append_is_eligible() -> None:
    run, revision = waiting_run(tool="delete_model", args={"name": "qwen"})
    rejects(
        lambda: verify_agent3_approval(
            token_for(run, revision),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "restricted to note_append",
    )


def test_bad_signature_is_rejected() -> None:
    run, revision = waiting_run()
    token = token_for(run, revision)
    rejects(
        lambda: verify_agent3_approval(
            token[:-1] + ("A" if token[-1] != "A" else "B"),
            run,
            plan_revision=revision,
            now=NOW,
            secret_factory=lambda: SECRET,
        ),
        "signature",
    )


def test_nonce_is_durably_single_use_across_connections() -> None:
    run, revision = waiting_run()
    approval = verify_agent3_approval(
        token_for(run, revision),
        run,
        plan_revision=revision,
        now=NOW,
        secret_factory=lambda: SECRET,
    )
    with tempfile.TemporaryDirectory() as temp:
        db = os.path.join(temp, "approvals.db")
        consume_agent3_approval(approval, db_path=db, now=NOW)
        rejects(
            lambda: consume_agent3_approval(approval, db_path=db, now=NOW + 1),
            "already used",
        )


def test_required_switch_defaults_off_and_needs_exact_one() -> None:
    assert approval_required({}) is False
    assert approval_required({"KALIV_AGENT3_APPROVAL_REQUIRED": "0"}) is False
    assert approval_required({"KALIV_AGENT3_APPROVAL_REQUIRED": "true"}) is False
    assert approval_required({"KALIV_AGENT3_APPROVAL_REQUIRED": "1"}) is True


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"agent3 approval: {len(TESTS)} passed")
