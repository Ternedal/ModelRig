"""Backend-issued, device-bound approvals for Agent 3 append-only writes.

The worker never mints approval. A paired client asks the authenticated Go
backend to sign the exact waiting confirmation. The worker verifies the HMAC,
current immutable step, current replan revision and expiry, then durably
consumes both the random nonce and the immutable action before the orchestrator
may execute the write.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from .. import paths as _paths
from .core import AgentRun, RunState

APPROVAL_SECRET_ENV = "KALIV_AGENT3_APPROVAL_SECRET"
APPROVAL_REQUIRED_ENV = "KALIV_AGENT3_APPROVAL_REQUIRED"
MAX_TOKEN_LIFETIME_SECONDS = 180
_MAX_CLOCK_SKEW_SECONDS = 30
_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Agent3ApprovalError(ValueError):
    """A missing, invalid, expired, changed or already-used write approval."""


@dataclass(frozen=True)
class VerifiedAgent3Approval:
    nonce_sha256: str
    action_sha256: str
    token_sha256: str
    device_id: str
    run_id: str
    step_id: str
    tool: str
    args_sha256: str
    confirmation_digest: str
    plan_revision: int
    issued_at: int
    expires_at: int

    def audit_payload(self) -> dict[str, Any]:
        """Content-free attribution safe for the append-only run event ledger."""
        return {
            "device_id": self.device_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "plan_revision": self.plan_revision,
            "args_sha256": self.args_sha256,
            "confirmation_digest": self.confirmation_digest,
            "approval_action_sha256": self.action_sha256,
            "approval_nonce_sha256": self.nonce_sha256,
            "approval_token_sha256": self.token_sha256,
        }


def approval_required(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get("KALIV_AGENT3_APPROVAL_REQUIRED") or "").strip() == "1"


def _secret() -> bytes:
    raw = os.getenv(APPROVAL_SECRET_ENV, "").encode("utf-8")
    if len(raw) < 32:
        raise Agent3ApprovalError(
            f"{APPROVAL_SECRET_ENV} must be the same random secret in backend and worker "
            "(minimum 32 bytes)"
        )
    return raw


def _b64decode(value: str) -> bytes:
    if not value or any(ch.isspace() for ch in value):
        raise Agent3ApprovalError("Agent 3 approval token is malformed")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001 - one fail-closed parse error
        raise Agent3ApprovalError("Agent 3 approval token is malformed") from exc


def _args_sha256(args: Any) -> str:
    """Hash the only approved write payload identically in Go and Python.

    Generic JSON canonicalization differs across runtimes for number rendering
    and escaping. This approval is intentionally restricted to note_append,
    whose executable payload is one bounded UTF-8 string. Bind exactly that
    string and reject every broader argument shape. The immutable confirmation
    digest independently binds the complete step object too.
    """
    if not isinstance(args, dict) or set(args) != {"text"}:
        raise Agent3ApprovalError("note_append approval requires exactly one text argument")
    text = args.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 10_000:
        raise Agent3ApprovalError("note_append approval text is invalid")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _action_sha256(run_id: str, step_id: str, digest: str, revision: int) -> str:
    raw = json.dumps(
        {
            "run_id": run_id,
            "step_id": step_id,
            "confirmation_digest": digest,
            "plan_revision": revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_agent3_approval(
    token: str | None,
    run: AgentRun,
    *,
    plan_revision: int,
    now: float | None = None,
    secret_factory: Callable[[], bytes] = _secret,
) -> VerifiedAgent3Approval:
    """Verify a backend approval against the exact current write checkpoint."""
    if not token:
        raise Agent3ApprovalError(
            "Agent 3 writes require a short-lived approval token issued after confirmation"
        )
    if run.state != RunState.WAITING_CONFIRMATION:
        raise Agent3ApprovalError("run is not waiting for confirmation")
    if run.current_step < 0 or run.current_step >= len(run.steps):
        raise Agent3ApprovalError("run has no current confirmation step")
    step = run.steps[run.current_step]
    if step.tool != "note_append":
        raise Agent3ApprovalError("this pilot approval is restricted to note_append")
    if step.confirmation_digest is None or step.confirmation_expires_at is None:
        raise Agent3ApprovalError("current step has no live immutable confirmation")
    if isinstance(plan_revision, bool) or not isinstance(plan_revision, int) or plan_revision < 0:
        raise Agent3ApprovalError("current plan revision is invalid")

    parts = token.split(".")
    if len(parts) != 2:
        raise Agent3ApprovalError("Agent 3 approval token is malformed")
    payload_part, signature_part = parts
    payload_raw = _b64decode(payload_part)
    signature = _b64decode(signature_part)
    mac = hmac.new(secret_factory(), payload_part.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(mac, signature):
        raise Agent3ApprovalError("Agent 3 approval token signature is invalid")

    try:
        claims = json.loads(payload_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Agent3ApprovalError("Agent 3 approval token payload is invalid") from exc
    if not isinstance(claims, dict) or claims.get("v") != 1:
        raise Agent3ApprovalError("Agent 3 approval token version is unsupported")

    nonce = claims.get("nonce")
    device_id = claims.get("device_id")
    issued_at = claims.get("issued_at")
    expires_at = claims.get("expires_at")
    claim_revision = claims.get("plan_revision")
    args_sha256 = claims.get("args_sha256")
    confirmation_digest = claims.get("confirmation_digest")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise Agent3ApprovalError("Agent 3 approval token nonce is invalid")
    if not isinstance(device_id, str) or not device_id.strip():
        raise Agent3ApprovalError("Agent 3 approval token is not bound to a device")
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise Agent3ApprovalError("Agent 3 approval token issue time is invalid")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise Agent3ApprovalError("Agent 3 approval token expiry is invalid")
    if isinstance(claim_revision, bool) or not isinstance(claim_revision, int):
        raise Agent3ApprovalError("Agent 3 approval plan revision is invalid")
    if not isinstance(args_sha256, str) or not _SHA256.fullmatch(args_sha256):
        raise Agent3ApprovalError("Agent 3 approval args binding is invalid")
    if not isinstance(confirmation_digest, str) or not _SHA256.fullmatch(confirmation_digest):
        raise Agent3ApprovalError("Agent 3 approval confirmation binding is invalid")

    current = time.time() if now is None else now
    if issued_at > current + _MAX_CLOCK_SKEW_SECONDS:
        raise Agent3ApprovalError("Agent 3 approval token is not valid yet")
    if expires_at <= current:
        raise Agent3ApprovalError("Agent 3 approval token has expired; confirm the action again")
    if expires_at <= issued_at or expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
        raise Agent3ApprovalError("Agent 3 approval token lifetime is invalid")
    if expires_at > int(step.confirmation_expires_at):
        raise Agent3ApprovalError("Agent 3 approval outlives the confirmation it authorizes")

    expected = {
        "run_id": run.id,
        "step_id": step.id,
        "tool": step.tool,
        "args_sha256": _args_sha256(step.args),
        "confirmation_digest": step.confirmation_digest,
        "plan_revision": plan_revision,
    }
    for name, value in expected.items():
        if claims.get(name) != value:
            raise Agent3ApprovalError(
                "Agent 3 approval no longer matches the run, immutable step or plan revision"
            )

    return VerifiedAgent3Approval(
        nonce_sha256=hashlib.sha256(nonce.encode("ascii")).hexdigest(),
        action_sha256=_action_sha256(
            run.id,
            step.id,
            step.confirmation_digest,
            plan_revision,
        ),
        token_sha256=hashlib.sha256(token.encode("ascii")).hexdigest(),
        device_id=device_id.strip(),
        run_id=run.id,
        step_id=step.id,
        tool=step.tool,
        args_sha256=args_sha256,
        confirmation_digest=confirmation_digest,
        plan_revision=claim_revision,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def consume_agent3_approval(
    approval: VerifiedAgent3Approval,
    *,
    db_path: str | None = None,
    now: float | None = None,
) -> None:
    """Durably consume one nonce AND one immutable action before write starts."""
    path = db_path or _paths.resolve(
        "./kaliv-agent3-approvals.db", env="KALIV_AGENT3_APPROVAL_DB"
    )
    current = time.time() if now is None else now
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent3_approval_uses (
                   nonce_sha256 TEXT PRIMARY KEY,
                   action_sha256 TEXT NOT NULL UNIQUE,
                   used_at REAL NOT NULL,
                   run_id TEXT NOT NULL,
                   step_id TEXT NOT NULL,
                   device_id TEXT NOT NULL,
                   plan_revision INTEGER NOT NULL,
                   token_sha256 TEXT NOT NULL
               )"""
        )
        conn.execute(
            "DELETE FROM agent3_approval_uses WHERE used_at < ?",
            (current - 30 * 86400,),
        )
        try:
            conn.execute(
                """INSERT INTO agent3_approval_uses
                   (nonce_sha256, action_sha256, used_at, run_id, step_id,
                    device_id, plan_revision, token_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    approval.nonce_sha256,
                    approval.action_sha256,
                    current,
                    approval.run_id,
                    approval.step_id,
                    approval.device_id,
                    approval.plan_revision,
                    approval.token_sha256,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise Agent3ApprovalError(
                "Agent 3 approval or immutable action was already used; confirm the action again"
            ) from exc
    finally:
        conn.close()
