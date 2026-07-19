"""Dormant common gate for local data sent to external read services.

No route, tool, connector or network client imports this module yet.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

POLICY_SCHEMA = "kaliv-data-sharing-policy/v1"
REQUEST_SCHEMA = "kaliv-data-sharing-request/v1"
PERMISSION_SCHEMA = "kaliv-data-sharing-permission/v1"
RECEIPT_SCHEMA = "kaliv-data-sharing-receipt/v1"

Category = Literal["public", "operational", "private", "secret"]
DestinationType = Literal["public_web", "cloud_model", "connector"]
Surface = Literal["agent_v2", "agent3", "research", "connector"]
Decision = Literal["automatic", "confirmation_required", "forbidden"]
Outcome = Literal["completed", "failed", "blocked", "local_fallback"]

_CATEGORIES = {"public", "operational", "private", "secret"}
_DESTINATIONS = {"public_web", "cloud_model", "connector"}
_SURFACES = {"agent_v2", "agent3", "research", "connector"}
_DECISIONS = {"automatic", "confirmation_required", "forbidden"}
_OUTCOMES = {"completed", "failed", "blocked", "local_fallback"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_DEST = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class DataSharingContractError(ValueError):
    pass


class DataSharingDenied(PermissionError):
    pass


def _text(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise DataSharingContractError(f"{name} must be a string")
    value = " ".join(value.split())
    if not value or len(value) > maximum:
        raise DataSharingContractError(f"{name} must contain 1..{maximum} characters")
    return value


def _slug(value: str, name: str) -> str:
    value = _text(value, name, 128).lower()
    if not _SLUG.fullmatch(value):
        raise DataSharingContractError(f"{name} has an invalid format")
    return value


def _destination(value: str) -> str:
    value = _text(value, "destination", 256).lower()
    if not _DEST.fullmatch(value) or any(mark in value for mark in ("?", "#", "@")):
        raise DataSharingContractError("destination must be a stable identifier without userinfo/query")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DataSharingPolicy:
    public: Decision = "automatic"
    operational: Decision = "confirmation_required"
    private: Decision = "confirmation_required"
    secret: Decision = "forbidden"
    schema: str = POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != POLICY_SCHEMA:
            raise DataSharingContractError("unsupported policy schema")
        if any(value not in _DECISIONS for value in self.rules().values()):
            raise DataSharingContractError("unsupported policy decision")
        if self.secret != "forbidden":
            raise DataSharingContractError("secret data must always be forbidden")
        if self.private == "automatic":
            raise DataSharingContractError("private data must never be automatic")

    def rules(self) -> dict[Category, Decision]:
        return {
            "public": self.public,
            "operational": self.operational,
            "private": self.private,
            "secret": self.secret,
        }

    def decision(self, request: "DataSharingRequest") -> Decision:
        return self.rules()[request.data_category]

    def to_dict(self) -> dict:
        return {"schema": self.schema, "rules": self.rules()}


DEFAULT_POLICY = DataSharingPolicy()


@dataclass(frozen=True)
class DataSharingRequest:
    surface: Surface
    destination_type: DestinationType
    provider: str
    destination: str
    data_category: Category
    purpose_code: str
    purpose: str
    summary: str
    content_sha256: str
    max_bytes: int
    schema: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise DataSharingContractError("unsupported request schema")
        if self.surface not in _SURFACES:
            raise DataSharingContractError("surface is invalid")
        if self.destination_type not in _DESTINATIONS:
            raise DataSharingContractError("destination_type is invalid")
        if self.data_category not in _CATEGORIES:
            raise DataSharingContractError("data_category is invalid")
        if not isinstance(self.content_sha256, str) or not _SHA256.fullmatch(self.content_sha256):
            raise DataSharingContractError("content_sha256 must be a lowercase SHA-256 digest")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int):
            raise DataSharingContractError("max_bytes must be an integer")
        if not 1 <= self.max_bytes <= 10_000_000:
            raise DataSharingContractError("max_bytes must be between 1 and 10000000")
        object.__setattr__(self, "provider", _slug(self.provider, "provider"))
        object.__setattr__(self, "destination", _destination(self.destination))
        object.__setattr__(self, "purpose_code", _slug(self.purpose_code, "purpose_code"))
        object.__setattr__(self, "purpose", _text(self.purpose, "purpose", 500))
        object.__setattr__(self, "summary", _text(self.summary, "summary", 180))

    @property
    def purpose_sha256(self) -> str:
        return _digest(self.purpose)

    @property
    def summary_sha256(self) -> str:
        return _digest(self.summary)

    def digest_payload(self) -> dict:
        return {
            "schema": self.schema,
            "surface": self.surface,
            "destination_type": self.destination_type,
            "provider": self.provider,
            "destination": self.destination,
            "data_category": self.data_category,
            "purpose_code": self.purpose_code,
            "purpose_sha256": self.purpose_sha256,
            "summary_sha256": self.summary_sha256,
            "content_sha256": self.content_sha256,
            "max_bytes": self.max_bytes,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.digest_payload())).hexdigest()

    def preview(self, policy: DataSharingPolicy = DEFAULT_POLICY) -> dict:
        return {
            "schema": self.schema,
            "request_digest": self.digest,
            "decision": policy.decision(self),
            "surface": self.surface,
            "destination_type": self.destination_type,
            "provider": self.provider,
            "destination": self.destination,
            "data_category": self.data_category,
            "purpose_code": self.purpose_code,
            "purpose": self.purpose,
            "summary": self.summary,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True)
class PermissionProposal:
    permission_id: str
    request_digest: str
    created_at: int
    expires_at: int
    preview: dict
    schema: str = PERMISSION_SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "permission_id": self.permission_id,
            "request_digest": self.request_digest,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "status": "pending",
            "preview": self.preview,
        }


@dataclass(frozen=True)
class DataSharingReceipt:
    receipt_id: str
    request_digest: str
    authorization: Literal["automatic", "permission"]
    permission_id: str | None
    authorized_at: int
    expires_at: int
    max_bytes: int
    schema: str = RECEIPT_SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "authorization": self.authorization,
            "permission_id": self.permission_id,
            "authorized_at": _iso(self.authorized_at),
            "expires_at": _iso(self.expires_at),
            "max_bytes": self.max_bytes,
        }


class DataSharingLedger:
    """Exact-request permissions and one-use receipts. Audit stores hashes, never data."""

    def __init__(self, path: str = ":memory:", *, uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4):
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sharing_permissions (
              permission_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
              surface TEXT NOT NULL, destination_type TEXT NOT NULL,
              provider TEXT NOT NULL, destination TEXT NOT NULL,
              data_category TEXT NOT NULL, purpose_code TEXT NOT NULL,
              purpose_sha256 TEXT NOT NULL, summary_sha256 TEXT NOT NULL,
              content_sha256 TEXT NOT NULL, max_bytes INTEGER NOT NULL,
              created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
              status TEXT NOT NULL, approved_by TEXT, approved_at INTEGER,
              revoked_by TEXT, revoked_at INTEGER, consumed_at INTEGER);
            CREATE TABLE IF NOT EXISTS sharing_receipts (
              receipt_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
              permission_id TEXT, authorization TEXT NOT NULL,
              max_bytes INTEGER NOT NULL, authorized_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL, status TEXT NOT NULL,
              claimed_at INTEGER, finished_at INTEGER, outcome TEXT,
              bytes_sent INTEGER, error_code TEXT,
              FOREIGN KEY(permission_id) REFERENCES sharing_permissions(permission_id));
            CREATE TABLE IF NOT EXISTS sharing_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
              event_type TEXT NOT NULL, request_digest TEXT NOT NULL,
              permission_id TEXT, receipt_id TEXT, surface TEXT NOT NULL,
              destination_type TEXT NOT NULL, provider TEXT NOT NULL,
              destination TEXT NOT NULL, data_category TEXT NOT NULL,
              purpose_code TEXT NOT NULL, purpose_sha256 TEXT NOT NULL,
              summary_sha256 TEXT NOT NULL, content_sha256 TEXT NOT NULL,
              max_bytes INTEGER NOT NULL, bytes_sent INTEGER,
              outcome TEXT, error_code TEXT);
            """
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{self._uuid_factory().hex}"

    @staticmethod
    def _now(value: int | None) -> int:
        value = int(time.time()) if value is None else value
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DataSharingContractError("now must be a non-negative integer")
        return value

    @staticmethod
    def _ttl(value: int, name: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise DataSharingContractError(f"{name} must be between 1 and {maximum} seconds")
        return value

    def _event(
        self, request: DataSharingRequest, *, now: int, event_type: str,
        permission_id: str | None = None, receipt_id: str | None = None,
        bytes_sent: int | None = None, outcome: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._db.execute(
            "INSERT INTO sharing_events VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now, event_type, request.digest, permission_id, receipt_id,
                request.surface, request.destination_type, request.provider,
                request.destination, request.data_category, request.purpose_code,
                request.purpose_sha256, request.summary_sha256,
                request.content_sha256, request.max_bytes, bytes_sent, outcome,
                error_code,
            ),
        )

    def propose(
        self, request: DataSharingRequest, *, policy: DataSharingPolicy = DEFAULT_POLICY,
        now: int | None = None, ttl_seconds: int = 300,
    ) -> PermissionProposal:
        now = self._now(now)
        ttl = self._ttl(ttl_seconds, "permission ttl", 3600)
        decision = policy.decision(request)
        if decision == "forbidden":
            with self._lock:
                self._event(request, now=now, event_type="permission_denied", outcome="policy")
            raise DataSharingDenied("policy forbids external processing")
        if decision == "automatic":
            raise DataSharingContractError("automatic requests do not use permission proposals")
        permission_id = self._id("dsp")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO sharing_permissions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        permission_id, request.digest, request.surface,
                        request.destination_type, request.provider, request.destination,
                        request.data_category, request.purpose_code,
                        request.purpose_sha256, request.summary_sha256,
                        request.content_sha256, request.max_bytes, now, now + ttl,
                        "pending", None, None, None, None, None,
                    ),
                )
                self._event(
                    request, now=now, event_type="permission_proposed",
                    permission_id=permission_id,
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return PermissionProposal(permission_id, request.digest, now, now + ttl, request.preview(policy))

    def approve(self, permission_id: str, *, actor: str, now: int | None = None) -> None:
        self._permission_transition(permission_id, _text(actor, "actor", 100), self._now(now), "approved")

    def deny(self, permission_id: str, *, actor: str, now: int | None = None) -> None:
        self._permission_transition(permission_id, _text(actor, "actor", 100), self._now(now), "denied")

    def revoke(self, permission_id: str, *, actor: str, now: int | None = None) -> None:
        self._permission_transition(permission_id, _text(actor, "actor", 100), self._now(now), "revoked")

    def _permission_transition(self, permission_id: str, actor: str, now: int, target: str) -> None:
        allowed = {
            "approved": {"pending"}, "denied": {"pending"},
            "revoked": {"pending", "approved"},
        }
        if target not in allowed:
            raise DataSharingContractError("invalid permission transition")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM sharing_permissions WHERE permission_id=?", (permission_id,)
                ).fetchone()
                if row is None:
                    raise DataSharingDenied("unknown permission")
                if row["expires_at"] <= now and row["status"] in {"pending", "approved"}:
                    self._db.execute(
                        "UPDATE sharing_permissions SET status='expired' WHERE permission_id=?",
                        (permission_id,),
                    )
                    raise DataSharingDenied("permission expired")
                if row["status"] not in allowed[target]:
                    raise DataSharingDenied(f"permission cannot transition to {target}")
                if target == "approved":
                    self._db.execute(
                        "UPDATE sharing_permissions SET status='approved', approved_by=?, approved_at=? "
                        "WHERE permission_id=? AND status='pending'", (actor, now, permission_id),
                    )
                else:
                    self._db.execute(
                        f"UPDATE sharing_permissions SET status=?, revoked_by=?, revoked_at=? "
                        f"WHERE permission_id=? AND status IN "
                        f"({'?,?' if target == 'revoked' else '?'})",
                        ((target, actor, now, permission_id, "pending", "approved")
                         if target == "revoked"
                         else (target, actor, now, permission_id, "pending")),
                    )
                self._event_from_row(row, now, f"permission_{target}", permission_id)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def authorize(
        self, request: DataSharingRequest, *, policy: DataSharingPolicy = DEFAULT_POLICY,
        permission_id: str | None = None, now: int | None = None,
        receipt_ttl_seconds: int = 60,
    ) -> DataSharingReceipt:
        now = self._now(now)
        ttl = self._ttl(receipt_ttl_seconds, "receipt ttl", 300)
        decision = policy.decision(request)
        if decision == "forbidden":
            with self._lock:
                self._event(request, now=now, event_type="authorization_denied", outcome="policy")
            raise DataSharingDenied("policy forbids external processing")
        authorization: Literal["automatic", "permission"] = "automatic"
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if decision == "confirmation_required":
                    if permission_id is None:
                        raise DataSharingDenied("exact permission is required")
                    row = self._db.execute(
                        "SELECT * FROM sharing_permissions WHERE permission_id=?", (permission_id,)
                    ).fetchone()
                    if row is None or row["request_digest"] != request.digest:
                        raise DataSharingDenied("permission does not match the exact request")
                    if row["status"] != "approved":
                        raise DataSharingDenied("permission is not approved")
                    if row["expires_at"] <= now:
                        self._db.execute(
                            "UPDATE sharing_permissions SET status='expired' WHERE permission_id=?",
                            (permission_id,),
                        )
                        raise DataSharingDenied("permission expired")
                    changed = self._db.execute(
                        "UPDATE sharing_permissions SET status='consumed', consumed_at=? "
                        "WHERE permission_id=? AND status='approved'", (now, permission_id),
                    ).rowcount
                    if changed != 1:
                        raise DataSharingDenied("permission was already consumed")
                    authorization = "permission"
                elif permission_id is not None:
                    raise DataSharingContractError("automatic authorization cannot attach permission")
                receipt_id = self._id("dsr")
                self._db.execute(
                    "INSERT INTO sharing_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt_id, request.digest, permission_id, authorization,
                        request.max_bytes, now, now + ttl, "authorized",
                        None, None, None, None, None,
                    ),
                )
                self._event(
                    request, now=now, event_type="authorized",
                    permission_id=permission_id, receipt_id=receipt_id,
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return DataSharingReceipt(
            receipt_id, request.digest, authorization, permission_id,
            now, now + ttl, request.max_bytes,
        )

    def claim(self, receipt: DataSharingReceipt, request: DataSharingRequest, *, now: int | None = None) -> None:
        now = self._now(now)
        if receipt.schema != RECEIPT_SCHEMA or receipt.request_digest != request.digest:
            raise DataSharingDenied("receipt does not match exact request")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM sharing_receipts WHERE receipt_id=?", (receipt.receipt_id,)
                ).fetchone()
                if row is None or row["request_digest"] != request.digest:
                    raise DataSharingDenied("unknown or mismatched receipt")
                if row["status"] != "authorized":
                    raise DataSharingDenied("receipt is not claimable")
                if row["expires_at"] <= now:
                    self._db.execute(
                        "UPDATE sharing_receipts SET status='expired' WHERE receipt_id=?",
                        (receipt.receipt_id,),
                    )
                    raise DataSharingDenied("receipt expired")
                if self._db.execute(
                    "UPDATE sharing_receipts SET status='in_flight', claimed_at=? "
                    "WHERE receipt_id=? AND status='authorized'", (now, receipt.receipt_id),
                ).rowcount != 1:
                    raise DataSharingDenied("receipt was already claimed")
                self._event(
                    request, now=now, event_type="claimed",
                    permission_id=receipt.permission_id, receipt_id=receipt.receipt_id,
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def complete(
        self, receipt: DataSharingReceipt, request: DataSharingRequest, *,
        outcome: Outcome, bytes_sent: int, error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        now = self._now(now)
        if receipt.request_digest != request.digest:
            raise DataSharingDenied("receipt does not match exact request")
        if outcome not in _OUTCOMES:
            raise DataSharingContractError("outcome is invalid")
        if isinstance(bytes_sent, bool) or not isinstance(bytes_sent, int) or bytes_sent < 0:
            raise DataSharingContractError("bytes_sent must be a non-negative integer")
        if bytes_sent > request.max_bytes:
            raise DataSharingDenied("byte budget exceeded")
        if error_code is not None and not _CODE.fullmatch(error_code):
            raise DataSharingContractError("error_code has an invalid format")
        if outcome == "completed" and error_code is not None:
            raise DataSharingContractError("completed outcome cannot include error_code")
        if outcome == "local_fallback" and bytes_sent:
            raise DataSharingContractError("local fallback must send zero bytes")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT status FROM sharing_receipts WHERE receipt_id=?", (receipt.receipt_id,)
                ).fetchone()
                if row is None or row["status"] != "in_flight":
                    raise DataSharingDenied("receipt is not in flight")
                self._db.execute(
                    "UPDATE sharing_receipts SET status='finished', finished_at=?, outcome=?, "
                    "bytes_sent=?, error_code=? WHERE receipt_id=?",
                    (now, outcome, bytes_sent, error_code, receipt.receipt_id),
                )
                self._event(
                    request, now=now, event_type="finished",
                    permission_id=receipt.permission_id, receipt_id=receipt.receipt_id,
                    bytes_sent=bytes_sent, outcome=outcome, error_code=error_code,
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def record_local_fallback(
        self, request: DataSharingRequest, *, reason_code: str, now: int | None = None,
    ) -> None:
        if not isinstance(reason_code, str) or not _CODE.fullmatch(reason_code):
            raise DataSharingContractError("reason_code has an invalid format")
        with self._lock:
            self._event(
                request, now=self._now(now), event_type="local_fallback",
                bytes_sent=0, outcome="local_fallback", error_code=reason_code,
            )

    def recent_events(self, limit: int = 50) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise DataSharingContractError("limit must be between 1 and 500")
        with self._lock:
            return [
                dict(row) for row in self._db.execute(
                    "SELECT * FROM sharing_events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    def _event_from_row(self, row: sqlite3.Row, now: int, event_type: str, permission_id: str) -> None:
        self._db.execute(
            "INSERT INTO sharing_events VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now, event_type, row["request_digest"], permission_id, None,
                row["surface"], row["destination_type"], row["provider"],
                row["destination"], row["data_category"], row["purpose_code"],
                row["purpose_sha256"], row["summary_sha256"],
                row["content_sha256"], row["max_bytes"], None, None, None,
            ),
        )
