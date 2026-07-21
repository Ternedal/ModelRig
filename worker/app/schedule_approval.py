"""Verify and consume backend-issued approvals for scheduled writes.

The public worker API deliberately does not mint approvals. A paired client asks
its authenticated Go backend for a short-lived token only after the human has
confirmed the preview. The backend signs the exact preview terms with a shared
secret; this module verifies that signature at the loopback worker boundary and
records the random nonce before a standing grant is persisted.

A token therefore proves more than knowledge of ``tool`` and ``args``:

* it was issued by the authenticated backend,
* it is bound to one create/renew preview and one paired device,
* it expires after minutes, and
* its random nonce can be consumed only once, durably across worker restarts.
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

from . import paths as _paths

APPROVAL_SECRET_ENV = "KALIV_SCHEDULER_APPROVAL_SECRET"
MAX_TOKEN_LIFETIME_SECONDS = 180
_MAX_CLOCK_SKEW_SECONDS = 30
_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")


class ScheduleApprovalError(ValueError):
    """A missing, invalid, expired or already-consumed approval token."""


@dataclass(frozen=True)
class VerifiedScheduleApproval:
    nonce: str
    device_id: str
    issued_at: int
    expires_at: int


def _b64decode(value: str) -> bytes:
    if not value or any(ch.isspace() for ch in value):
        raise ScheduleApprovalError("schedule approval token is malformed")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001 - one fail-closed parse error
        raise ScheduleApprovalError("schedule approval token is malformed") from exc


def _secret() -> bytes:
    raw = os.getenv(APPROVAL_SECRET_ENV, "").encode("utf-8")
    if len(raw) < 32:
        raise ScheduleApprovalError(
            f"{APPROVAL_SECRET_ENV} must be the same random secret in backend and worker (minimum 32 bytes)"
        )
    return raw


def verify_schedule_approval(
    token: str | None,
    preview: Any,
    *,
    now: float | None = None,
    secret_factory: Callable[[], bytes] = _secret,
) -> VerifiedScheduleApproval:
    """Verify a backend token against the exact canonical worker preview."""
    if not token:
        raise ScheduleApprovalError(
            "scheduled writes require a short-lived approval token issued after confirmation"
        )
    if not getattr(preview, "requires_approval", False):
        raise ScheduleApprovalError("approval tokens are only valid for write schedules")

    parts = token.split(".")
    if len(parts) != 2:
        raise ScheduleApprovalError("schedule approval token is malformed")
    payload_part, signature_part = parts
    payload_raw = _b64decode(payload_part)
    signature = _b64decode(signature_part)

    mac = hmac.new(secret_factory(), payload_part.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(mac, signature):
        raise ScheduleApprovalError("schedule approval token signature is invalid")

    try:
        claims = json.loads(payload_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScheduleApprovalError("schedule approval token payload is invalid") from exc
    if not isinstance(claims, dict):
        raise ScheduleApprovalError("schedule approval token payload is invalid")
    version = claims.get("v")
    if version != 2:
        raise ScheduleApprovalError("schedule approval token version is unsupported")

    nonce = claims.get("nonce")
    device_id = claims.get("device_id")
    issued_at = claims.get("issued_at")
    expires_at = claims.get("expires_at")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ScheduleApprovalError("schedule approval token nonce is invalid")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ScheduleApprovalError("schedule approval token is not bound to a device")
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise ScheduleApprovalError("schedule approval token issue time is invalid")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ScheduleApprovalError("schedule approval token expiry is invalid")

    current = time.time() if now is None else now
    if issued_at > current + _MAX_CLOCK_SKEW_SECONDS:
        raise ScheduleApprovalError("schedule approval token is not valid yet")
    if expires_at <= current:
        raise ScheduleApprovalError("schedule approval token has expired; confirm the preview again")
    if expires_at <= issued_at or expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
        raise ScheduleApprovalError("schedule approval token lifetime is invalid")

    preview_timezone = getattr(preview, "timezone", None)
    preview_misfire = getattr(preview, "misfire_policy", None)

    expected = {
        "operation": getattr(preview, "operation", None),
        "schedule_id": getattr(preview, "schedule_id", None),
        "tool": getattr(preview, "tool", None),
        "args": getattr(preview, "args", None),
        "cadence": getattr(preview, "cadence", None),
        "timezone": preview_timezone,
        "misfire_policy": preview_misfire,
        "ttl_days": getattr(preview, "ttl_days", None),
        "max_runs": getattr(preview, "max_runs", None),
        "enable": getattr(preview, "enable", None),
        "action_fingerprint": getattr(preview, "action_fingerprint", None),
        "approval_fingerprint": getattr(preview, "approval_fingerprint", None),
    }
    for name, value in expected.items():
        if claims.get(name) != value:
            raise ScheduleApprovalError(
                "schedule approval does not match the previewed action, cadence, timezone, misfire policy, expiry, budget or enable state"
            )

    return VerifiedScheduleApproval(
        nonce=nonce,
        device_id=device_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def consume_schedule_approval(
    nonce: str,
    *,
    db_path: str | None = None,
    now: float | None = None,
) -> None:
    """Durably consume one random approval nonce exactly once."""
    path = db_path or _paths.resolve(
        "./kaliv-schedules.db", env="KALIV_SCHEDULES_DB"
    )
    current = time.time() if now is None else now
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schedule_approval_uses (
                   nonce TEXT PRIMARY KEY,
                   used_at REAL NOT NULL
               )"""
        )
        # Expired tokens are rejected before this function. Retain used nonces
        # for a week rather than only one token lifetime so an ordinary clock
        # correction cannot resurrect a token whose row was just pruned.
        conn.execute(
            "DELETE FROM schedule_approval_uses WHERE used_at < ?",
            (current - 7 * 86400,),
        )
        try:
            conn.execute(
                "INSERT INTO schedule_approval_uses (nonce, used_at) VALUES (?, ?)",
                (nonce, current),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ScheduleApprovalError(
                "schedule approval token was already used; confirm the preview again"
            ) from exc
    finally:
        conn.close()
