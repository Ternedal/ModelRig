#!/usr/bin/env python3
"""T-017 worker v2-only approval contract for timezone-bound grants.

All issuers now use explicit v2 claims. Version 1 is rejected even for the
historical Copenhagen/run_once terms so no unsigned time defaults survive.
Run: PYTHONPATH=worker python3 tests/worker_schedule_approval_time.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_approval import (  # noqa: E402
    ScheduleApprovalError,
    verify_schedule_approval,
)

passed = failed = 0
SECRET = b"0123456789abcdef0123456789abcdef-t017-v2"
NOW = 1_800_000_000


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def preview(*, timezone="America/New_York", misfire_policy="run_once"):
    return SimpleNamespace(
        operation="create",
        schedule_id=None,
        tool="note_append",
        args={"text": "timezone grant"},
        cadence="daily:02:30",
        timezone=timezone,
        misfire_policy=misfire_policy,
        ttl_days=30,
        max_runs=5,
        enable=True,
        action_fingerprint="a" * 32,
        approval_fingerprint="b" * 32,
        requires_approval=True,
    )


def token_for(item, *, version=2, include_time=True, timezone=None, policy=None):
    claims = {
        "v": version,
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "device_id": "pixel-6a-t017-v2",
        "operation": item.operation,
        "schedule_id": item.schedule_id,
        "tool": item.tool,
        "args": item.args,
        "cadence": item.cadence,
        "ttl_days": item.ttl_days,
        "max_runs": item.max_runs,
        "enable": item.enable,
        "action_fingerprint": item.action_fingerprint,
        "approval_fingerprint": item.approval_fingerprint,
        "issued_at": NOW,
        "expires_at": NOW + 120,
    }
    if include_time:
        claims["timezone"] = item.timezone if timezone is None else timezone
        claims["misfire_policy"] = (
            item.misfire_policy if policy is None else policy
        )
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(SECRET, payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def refused(token, item, needle):
    try:
        verify_schedule_approval(
            token,
            item,
            now=NOW + 1,
            secret_factory=lambda: SECRET,
        )
        return False
    except ScheduleApprovalError as exc:
        return needle in str(exc)


nondefault = preview()
verified = verify_schedule_approval(
    token_for(nondefault),
    nondefault,
    now=NOW + 1,
    secret_factory=lambda: SECRET,
)
check(verified.device_id == "pixel-6a-t017-v2", "v2 verifies exact non-default timezone grant")
check(
    refused(
        token_for(nondefault, timezone="Europe/Copenhagen"),
        nondefault,
        "does not match",
    ),
    "v2 signed for another timezone is refused",
)
check(
    refused(
        token_for(nondefault, policy="skip"),
        nondefault,
        "does not match",
    ),
    "v2 signed for another misfire policy is refused",
)
check(
    refused(token_for(nondefault, include_time=False), nondefault, "does not match"),
    "v2 missing explicit time claims is refused",
)
legacy = preview(timezone="Europe/Copenhagen", misfire_policy="run_once")
check(
    refused(token_for(legacy, version=1, include_time=False), legacy, "version"),
    "v1 is rejected even for historical default terms",
)
check(
    refused(token_for(legacy, version=3), legacy, "version"),
    "unknown token version remains fail-closed",
)

print(f"\n===== SCHEDULE APPROVAL TIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
