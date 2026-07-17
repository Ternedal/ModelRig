"""Cryptographic and durable properties of scheduler approval tokens.

Run: PYTHONPATH=worker python3 tests/worker_schedule_approval.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_approval import (  # noqa: E402
    ScheduleApprovalError,
    consume_schedule_approval,
    verify_schedule_approval,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def token_for(preview, secret, *, now=1_800_000_000, nonce=None, device="phone"):
    claims = {
        "v": 1,
        "nonce": nonce or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "device_id": device,
        "operation": preview.operation,
        "schedule_id": preview.schedule_id,
        "tool": preview.tool,
        "args": preview.args,
        "cadence": preview.cadence,
        "ttl_days": preview.ttl_days,
        "max_runs": preview.max_runs,
        "enable": preview.enable,
        "action_fingerprint": preview.action_fingerprint,
        "approval_fingerprint": preview.approval_fingerprint,
        "issued_at": now,
        "expires_at": now + 120,
    }
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


secret = b"0123456789abcdef0123456789abcdef-test"
preview = SimpleNamespace(
    operation="create",
    schedule_id=None,
    tool="note_append",
    args={"text": "Husk brygdag"},
    cadence="daily:08:00",
    ttl_days=30,
    max_runs=5,
    enable=True,
    action_fingerprint="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    approval_fingerprint="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    requires_approval=True,
)
token = token_for(preview, secret)
verified = verify_schedule_approval(token, preview, now=1_800_000_001, secret_factory=lambda: secret)
check(bool(verified.nonce) and verified.device_id == "phone", "valid token verifies and carries device binding")

changed = SimpleNamespace(**vars(preview))
changed.max_runs = 6
try:
    verify_schedule_approval(token, changed, now=1_800_000_001, secret_factory=lambda: secret)
    mismatch_refused = False
except ScheduleApprovalError as exc:
    mismatch_refused = "does not match" in str(exc)
check(mismatch_refused, "changed budget invalidates signed approval")

parts = token.split(".")
forged_sig = ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
try:
    verify_schedule_approval(parts[0] + "." + forged_sig, preview, now=1_800_000_001, secret_factory=lambda: secret)
    forged_refused = False
except ScheduleApprovalError as exc:
    forged_refused = "signature" in str(exc)
check(forged_refused, "forged signature is refused")

try:
    verify_schedule_approval(token, preview, now=1_800_000_121, secret_factory=lambda: secret)
    expiry_refused = False
except ScheduleApprovalError as exc:
    expiry_refused = "expired" in str(exc)
check(expiry_refused, "token expires after its short lifetime")

read_preview = SimpleNamespace(**vars(preview))
read_preview.requires_approval = False
try:
    verify_schedule_approval(token, read_preview, now=1_800_000_001, secret_factory=lambda: secret)
    read_refused = False
except ScheduleApprovalError as exc:
    read_refused = "only valid for write" in str(exc)
check(read_refused, "write token cannot be laundered onto a read schedule")

path = os.path.join(tempfile.mkdtemp(prefix="schedule-approval-"), "schedules.db")
consume_schedule_approval(verified.nonce, db_path=path, now=1_800_000_001)
try:
    consume_schedule_approval(verified.nonce, db_path=path, now=1_800_000_002)
    replay_refused = False
except ScheduleApprovalError as exc:
    replay_refused = "already used" in str(exc)
check(replay_refused, "nonce is durably single-use")

print(f"\n===== SCHEDULE APPROVAL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
