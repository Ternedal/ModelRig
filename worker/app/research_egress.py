"""Dormant egress authorization, receipt and audit contract for web research.

Nothing in this module performs network I/O or registers a tool. It defines the
one-use authorization boundary that a later BrowserHost integration must cross
before sending data to a public network destination.
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

from .research_contract import ResearchContractError, normalize_domain_rule
from .tools import Sensitivity, may_egress

EGRESS_SCHEMA_VERSION = "modelrig.egress.v1"
_MAX_PURPOSE_CHARS = 500
_MAX_BYTES = 10_000_000
_MAX_ACTOR_CHARS = 100
_DESTINATION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ReceiptOutcome = Literal["completed", "failed", "blocked"]


class EgressContractError(ValueError):
    """The caller supplied an invalid egress plan or state transition."""


class EgressDenied(PermissionError):
    """Egress was refused by sensitivity, consent, expiry or receipt state."""


def _clean_text(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise EgressContractError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise EgressContractError(f"{name} must not be empty")
    if len(cleaned) > maximum:
        raise EgressContractError(f"{name} exceeds {maximum} characters")
    return cleaned


def _utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class EgressPlan:
    """Exact outbound intent. Consent binds to its digest, never to a broad tool."""

    destination: str
    purpose: str
    payload_sha256: str
    sensitivity: Sensitivity
    allowed_domains: tuple[str, ...]
    max_bytes: int
    schema_version: str = EGRESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EGRESS_SCHEMA_VERSION:
            raise EgressContractError("unsupported egress schema_version")
        destination = _clean_text(self.destination, name="destination", maximum=64).lower()
        if not _DESTINATION_RE.fullmatch(destination):
            raise EgressContractError("destination has an invalid format")
        purpose = _clean_text(self.purpose, name="purpose", maximum=_MAX_PURPOSE_CHARS)
        if not isinstance(self.payload_sha256, str) or not _SHA256_RE.fullmatch(self.payload_sha256):
            raise EgressContractError("payload_sha256 must be a lowercase SHA-256 digest")
        if self.sensitivity not in {"public", "operational", "private", "secret"}:
            raise EgressContractError("sensitivity is invalid")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int):
            raise EgressContractError("max_bytes must be an integer")
        if not 1 <= self.max_bytes <= _MAX_BYTES:
            raise EgressContractError(f"max_bytes must be between 1 and {_MAX_BYTES}")
        try:
            domains = tuple(sorted(set(normalize_domain_rule(item) for item in self.allowed_domains)))
        except ResearchContractError as exc:
            raise EgressContractError("allowed_domains contains an invalid rule") from exc
        if not domains:
            raise EgressContractError("allowed_domains must not be empty")
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "allowed_domains", domains)

    @property
    def purpose_sha256(self) -> str:
        return hashlib.sha256(self.purpose.encode("utf-8")).hexdigest()

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.digest_payload())).hexdigest()

    def digest_payload(self) -> dict:
        """Canonical consent/audit payload; raw purpose text is deliberately absent."""
        return {
            "schema_version": self.schema_version,
            "destination": self.destination,
            "purpose_sha256": self.purpose_sha256,
            "payload_sha256": self.payload_sha256,
            "sensitivity": self.sensitivity,
            "allowed_domains": list(self.allowed_domains),
            "max_bytes": self.max_bytes,
        }

    def confirmation_payload(self) -> dict:
        """Human-facing proposal. This is returned, not persisted in the audit DB."""
        return {
            **self.digest_payload(),
            "purpose": self.purpose,
            "plan_digest": self.digest,
        }


@dataclass(frozen=True)
class ConsentProposal:
    proposal_id: str
    plan_digest: str
    created_at: int
    expires_at: int
    status: str

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "plan_digest": self.plan_digest,
            "created_at": _utc_iso(self.created_at),
            "expires_at": _utc_iso(self.expires_at),
            "status": self.status,
        }


@dataclass(frozen=True)
class EgressReceipt:
    receipt_id: str
    plan_digest: str
    authorized_at: int
    expires_at: int
    authorization: Literal["automatic", "consented"]
    consent_id: str | None
    max_bytes: int

    def to_dict(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "plan_digest": self.plan_digest,
            "authorized_at": _utc_iso(self.authorized_at),
            "expires_at": _utc_iso(self.expires_at),
            "authorization": self.authorization,
            "consent_id": self.consent_id,
            "max_bytes": self.max_bytes,
        }


class EgressLedger:
    """SQLite-backed one-use consent and egress receipt state machine.

    The event table is append-only and stores no raw query/purpose/payload.
    Proposal and receipt rows may only move forward through explicit states.
    """

    def __init__(
        self,
        path: str = ":memory:",
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.path = path
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS egress_proposals (
                proposal_id TEXT PRIMARY KEY,
                plan_digest TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                destination TEXT NOT NULL,
                allowed_domains_json TEXT NOT NULL,
                purpose_sha256 TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                max_bytes INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                approved_by TEXT,
                approved_at INTEGER,
                consumed_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS egress_receipts (
                receipt_id TEXT PRIMARY KEY,
                plan_digest TEXT NOT NULL,
                consent_id TEXT,
                authorization TEXT NOT NULL,
                max_bytes INTEGER NOT NULL,
                authorized_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                claimed_at INTEGER,
                finished_at INTEGER,
                outcome TEXT,
                bytes_sent INTEGER,
                error_code TEXT,
                FOREIGN KEY(consent_id) REFERENCES egress_proposals(proposal_id)
            );
            CREATE TABLE IF NOT EXISTS egress_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                plan_digest TEXT NOT NULL,
                proposal_id TEXT,
                receipt_id TEXT,
                sensitivity TEXT NOT NULL,
                destination TEXT NOT NULL,
                allowed_domains_json TEXT NOT NULL,
                purpose_sha256 TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                max_bytes INTEGER NOT NULL,
                bytes_sent INTEGER,
                outcome TEXT,
                error_code TEXT
            );
            """
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{self._uuid_factory().hex}"

    @staticmethod
    def _now(now: int | None) -> int:
        value = int(time.time()) if now is None else now
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EgressContractError("now must be a non-negative integer timestamp")
        return value

    @staticmethod
    def _ttl(value: int, *, name: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise EgressContractError(f"{name} must be between 1 and {maximum} seconds")
        return value

    def _event(
        self,
        plan: EgressPlan,
        *,
        now: int,
        event_type: str,
        proposal_id: str | None = None,
        receipt_id: str | None = None,
        bytes_sent: int | None = None,
        outcome: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO egress_events (ts,event_type,plan_digest,proposal_id,receipt_id,"
            "sensitivity,destination,allowed_domains_json,purpose_sha256,payload_sha256,"
            "max_bytes,bytes_sent,outcome,error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now,
                event_type,
                plan.digest,
                proposal_id,
                receipt_id,
                plan.sensitivity,
                plan.destination,
                json.dumps(plan.allowed_domains, separators=(",", ":")),
                plan.purpose_sha256,
                plan.payload_sha256,
                plan.max_bytes,
                bytes_sent,
                outcome,
                error_code,
            ),
        )

    def propose(
        self,
        plan: EgressPlan,
        *,
        now: int | None = None,
        ttl_seconds: int = 300,
    ) -> ConsentProposal:
        timestamp = self._now(now)
        ttl = self._ttl(ttl_seconds, name="proposal ttl", maximum=3_600)
        if plan.sensitivity == "secret":
            with self._lock:
                self._event(plan, now=timestamp, event_type="proposal_denied", outcome="secret")
            raise EgressDenied("secret data may never egress")
        proposal_id = self._id("egc")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO egress_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        proposal_id,
                        plan.digest,
                        plan.sensitivity,
                        plan.destination,
                        json.dumps(plan.allowed_domains, separators=(",", ":")),
                        plan.purpose_sha256,
                        plan.payload_sha256,
                        plan.max_bytes,
                        timestamp,
                        timestamp + ttl,
                        "pending",
                        None,
                        None,
                        None,
                    ),
                )
                self._event(plan, now=timestamp, event_type="proposed", proposal_id=proposal_id)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return ConsentProposal(proposal_id, plan.digest, timestamp, timestamp + ttl, "pending")

    def approve(self, proposal_id: str, *, actor: str, now: int | None = None) -> None:
        timestamp = self._now(now)
        actor_value = _clean_text(actor, name="actor", maximum=_MAX_ACTOR_CHARS)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM egress_proposals WHERE proposal_id=?", (proposal_id,)
                ).fetchone()
                if row is None:
                    raise EgressDenied("unknown egress proposal")
                if row["status"] != "pending":
                    raise EgressDenied("egress proposal is not pending")
                if row["expires_at"] <= timestamp:
                    self._conn.execute(
                        "UPDATE egress_proposals SET status='expired' WHERE proposal_id=?",
                        (proposal_id,),
                    )
                    raise EgressDenied("egress proposal expired")
                self._conn.execute(
                    "UPDATE egress_proposals SET status='approved', approved_by=?, approved_at=? "
                    "WHERE proposal_id=? AND status='pending'",
                    (actor_value, timestamp, proposal_id),
                )
                self._event_from_row(row, now=timestamp, event_type="approved", proposal_id=proposal_id)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def deny(self, proposal_id: str, *, now: int | None = None) -> None:
        timestamp = self._now(now)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM egress_proposals WHERE proposal_id=?", (proposal_id,)
                ).fetchone()
                if row is None or row["status"] not in {"pending", "approved"}:
                    raise EgressDenied("egress proposal cannot be denied")
                self._conn.execute(
                    "UPDATE egress_proposals SET status='denied' WHERE proposal_id=?",
                    (proposal_id,),
                )
                self._event_from_row(row, now=timestamp, event_type="denied", proposal_id=proposal_id)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def authorize(
        self,
        plan: EgressPlan,
        *,
        consent_id: str | None = None,
        now: int | None = None,
        receipt_ttl_seconds: int = 60,
    ) -> EgressReceipt:
        timestamp = self._now(now)
        ttl = self._ttl(receipt_ttl_seconds, name="receipt ttl", maximum=300)
        if plan.sensitivity == "secret" or not may_egress(plan.sensitivity, consent=consent_id is not None):
            with self._lock:
                self._event(plan, now=timestamp, event_type="authorization_denied", outcome="sensitivity")
            raise EgressDenied("egress requires valid consent or is absolutely forbidden")

        authorization: Literal["automatic", "consented"] = "automatic"
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if plan.sensitivity == "private":
                    if not consent_id:
                        raise EgressDenied("private egress requires consent")
                    row = self._conn.execute(
                        "SELECT * FROM egress_proposals WHERE proposal_id=?", (consent_id,)
                    ).fetchone()
                    if row is None:
                        raise EgressDenied("unknown egress consent")
                    if row["plan_digest"] != plan.digest:
                        raise EgressDenied("egress consent does not match the exact plan")
                    if row["status"] != "approved":
                        raise EgressDenied("egress consent is not approved")
                    if row["expires_at"] <= timestamp:
                        self._conn.execute(
                            "UPDATE egress_proposals SET status='expired' WHERE proposal_id=?",
                            (consent_id,),
                        )
                        raise EgressDenied("egress consent expired")
                    updated = self._conn.execute(
                        "UPDATE egress_proposals SET status='consumed', consumed_at=? "
                        "WHERE proposal_id=? AND status='approved'",
                        (timestamp, consent_id),
                    ).rowcount
                    if updated != 1:
                        raise EgressDenied("egress consent was already consumed")
                    authorization = "consented"
                elif consent_id is not None:
                    raise EgressContractError("automatic egress must not attach an unrelated consent id")

                receipt_id = self._id("egr")
                self._conn.execute(
                    "INSERT INTO egress_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt_id,
                        plan.digest,
                        consent_id,
                        authorization,
                        plan.max_bytes,
                        timestamp,
                        timestamp + ttl,
                        "authorized",
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                self._event(
                    plan,
                    now=timestamp,
                    event_type="authorized",
                    proposal_id=consent_id,
                    receipt_id=receipt_id,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return EgressReceipt(
            receipt_id,
            plan.digest,
            timestamp,
            timestamp + ttl,
            authorization,
            consent_id,
            plan.max_bytes,
        )

    def claim(self, receipt: EgressReceipt, plan: EgressPlan, *, now: int | None = None) -> None:
        timestamp = self._now(now)
        if receipt.plan_digest != plan.digest:
            raise EgressDenied("receipt does not match the exact egress plan")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM egress_receipts WHERE receipt_id=?", (receipt.receipt_id,)
                ).fetchone()
                if row is None or row["plan_digest"] != plan.digest:
                    raise EgressDenied("unknown or mismatched egress receipt")
                if row["status"] != "authorized":
                    raise EgressDenied("egress receipt is not claimable")
                if row["expires_at"] <= timestamp:
                    self._conn.execute(
                        "UPDATE egress_receipts SET status='expired' WHERE receipt_id=?",
                        (receipt.receipt_id,),
                    )
                    raise EgressDenied("egress receipt expired")
                updated = self._conn.execute(
                    "UPDATE egress_receipts SET status='in_flight', claimed_at=? "
                    "WHERE receipt_id=? AND status='authorized'",
                    (timestamp, receipt.receipt_id),
                ).rowcount
                if updated != 1:
                    raise EgressDenied("egress receipt was already claimed")
                self._event(plan, now=timestamp, event_type="claimed", receipt_id=receipt.receipt_id)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def complete(
        self,
        receipt: EgressReceipt,
        plan: EgressPlan,
        *,
        outcome: ReceiptOutcome,
        bytes_sent: int,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = self._now(now)
        if receipt.plan_digest != plan.digest:
            raise EgressDenied("receipt does not match the exact egress plan")
        if outcome not in {"completed", "failed", "blocked"}:
            raise EgressContractError("outcome is invalid")
        if isinstance(bytes_sent, bool) or not isinstance(bytes_sent, int) or bytes_sent < 0:
            raise EgressContractError("bytes_sent must be a non-negative integer")
        if bytes_sent > plan.max_bytes:
            raise EgressDenied("egress exceeded its authorized byte budget")
        if error_code is not None and not _ERROR_CODE_RE.fullmatch(error_code):
            raise EgressContractError("error_code has an invalid format")
        if outcome == "completed" and error_code is not None:
            raise EgressContractError("completed egress must not include an error_code")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT status FROM egress_receipts WHERE receipt_id=?", (receipt.receipt_id,)
                ).fetchone()
                if row is None or row["status"] != "in_flight":
                    raise EgressDenied("egress receipt is not in flight")
                self._conn.execute(
                    "UPDATE egress_receipts SET status='finished', finished_at=?, outcome=?, "
                    "bytes_sent=?, error_code=? WHERE receipt_id=?",
                    (timestamp, outcome, bytes_sent, error_code, receipt.receipt_id),
                )
                self._event(
                    plan,
                    now=timestamp,
                    event_type="finished",
                    receipt_id=receipt.receipt_id,
                    bytes_sent=bytes_sent,
                    outcome=outcome,
                    error_code=error_code,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def recent_events(self, limit: int = 50) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise EgressContractError("limit must be between 1 and 500")
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM egress_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def _event_from_row(
        self,
        row: sqlite3.Row,
        *,
        now: int,
        event_type: str,
        proposal_id: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO egress_events (ts,event_type,plan_digest,proposal_id,receipt_id,"
            "sensitivity,destination,allowed_domains_json,purpose_sha256,payload_sha256,"
            "max_bytes,bytes_sent,outcome,error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now,
                event_type,
                row["plan_digest"],
                proposal_id,
                None,
                row["sensitivity"],
                row["destination"],
                row["allowed_domains_json"],
                row["purpose_sha256"],
                row["payload_sha256"],
                row["max_bytes"],
                None,
                None,
                None,
            ),
        )
