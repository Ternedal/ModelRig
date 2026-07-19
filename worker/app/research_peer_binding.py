"""Dormant public DNS/peer binding contract for web research.

This module performs no socket or browser I/O and registers no tool. A caller
injects a resolver, receives one short-lived binding for an already-authorized
egress plan, atomically claims it once, then proves the actual connected peer.
The SQLite audit stores URL hashes and network metadata, never raw query paths,
purposes or payloads.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Sequence
from urllib.parse import urlsplit

from .research_contract import ResearchContractError, canonicalize_url, host_allowed
from .research_egress import EgressPlan, EgressReceipt

PEER_BINDING_SCHEMA_VERSION = "modelrig.peer-binding.v1"
_MAX_DNS_ANSWERS = 32
_MAX_TTL_SECONDS = 300
_ERROR_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BindingOutcome = Literal["connected", "failed", "blocked"]
Resolver = Callable[[str, int], Sequence[str]]


class PeerBindingContractError(ValueError):
    """The caller supplied an invalid plan, receipt, URL or transition."""


class PeerBindingDenied(PermissionError):
    """DNS, expiry, one-use state or peer verification refused the request."""


def _utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _url_digest(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _dns_digest(host: str, port: int, addresses: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical_json({"host": host, "port": port, "addresses": list(addresses)})
    ).hexdigest()


def _public_address(value: str) -> str:
    if not isinstance(value, str):
        raise PeerBindingDenied("DNS returned an invalid address")
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise PeerBindingDenied("DNS returned an invalid address") from exc
    if not parsed.is_global:
        raise PeerBindingDenied("DNS returned a non-public address")
    return parsed.compressed


def _sort_addresses(values: Sequence[str]) -> tuple[str, ...]:
    if not values:
        raise PeerBindingDenied("DNS returned no addresses")
    if len(values) > _MAX_DNS_ANSWERS:
        raise PeerBindingDenied("DNS answer budget exceeded")
    normalized: list[str] = []
    for value in values:
        address = _public_address(value)
        if address not in normalized:
            normalized.append(address)
    normalized.sort(
        key=lambda value: (
            ipaddress.ip_address(value).version,
            ipaddress.ip_address(value).packed,
        )
    )
    if not normalized:
        raise PeerBindingDenied("DNS returned no addresses")
    return tuple(normalized)


def _validate_egress(plan: EgressPlan, receipt: EgressReceipt, now: int) -> None:
    if not isinstance(plan, EgressPlan):
        raise PeerBindingContractError("plan must be an EgressPlan")
    if not isinstance(receipt, EgressReceipt):
        raise PeerBindingContractError("receipt must be an EgressReceipt")
    if receipt.plan_digest != plan.digest:
        raise PeerBindingDenied("egress receipt does not match the plan")
    if receipt.max_bytes != plan.max_bytes:
        raise PeerBindingDenied("egress receipt byte ceiling does not match the plan")
    if receipt.expires_at <= now:
        raise PeerBindingDenied("egress receipt expired")


def _validate_url(plan: EgressPlan, raw_url: str) -> tuple[str, str, int]:
    try:
        canonical = canonicalize_url(raw_url)
        if not host_allowed(canonical, plan.allowed_domains):
            raise PeerBindingDenied("URL is outside the authorized domain scope")
        parsed = urlsplit(canonical)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ResearchContractError as exc:
        raise PeerBindingDenied("URL is outside the public research contract") from exc
    except ValueError as exc:
        raise PeerBindingContractError("URL has an invalid port") from exc
    host = parsed.hostname or ""
    if not host:
        raise PeerBindingContractError("URL is missing a host")
    return canonical, host, port


@dataclass(frozen=True)
class PublicPeerBinding:
    binding_id: str
    egress_receipt_id: str
    plan_digest: str
    url_sha256: str
    host: str
    port: int
    addresses: tuple[str, ...]
    selected_address: str
    dns_sha256: str
    issued_at: int
    expires_at: int
    schema_version: str = PEER_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PEER_BINDING_SCHEMA_VERSION:
            raise PeerBindingContractError("unsupported peer binding schema_version")
        if not isinstance(self.binding_id, str) or not self.binding_id.startswith("pbr_"):
            raise PeerBindingContractError("binding_id has an invalid format")
        if not isinstance(self.egress_receipt_id, str) or not self.egress_receipt_id:
            raise PeerBindingContractError("egress_receipt_id is invalid")
        for name, value in (
            ("plan_digest", self.plan_digest),
            ("url_sha256", self.url_sha256),
            ("dns_sha256", self.dns_sha256),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise PeerBindingContractError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise PeerBindingContractError("port is invalid")
        normalized = _sort_addresses(self.addresses)
        if normalized != self.addresses:
            raise PeerBindingContractError("addresses must be normalized and sorted")
        selected = _public_address(self.selected_address)
        if selected not in normalized:
            raise PeerBindingContractError("selected_address is not in addresses")
        if self.expires_at <= self.issued_at:
            raise PeerBindingContractError("binding expiry must follow issue time")
        if _dns_digest(self.host, self.port, normalized) != self.dns_sha256:
            raise PeerBindingContractError("dns_sha256 does not match the binding")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "egress_receipt_id": self.egress_receipt_id,
            "plan_digest": self.plan_digest,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "addresses": list(self.addresses),
            "selected_address": self.selected_address,
            "dns_sha256": self.dns_sha256,
            "issued_at": _utc_iso(self.issued_at),
            "expires_at": _utc_iso(self.expires_at),
        }


class PublicPeerLedger:
    """SQLite-backed, one-use DNS and connected-peer evidence ledger."""

    def __init__(
        self,
        resolver: Resolver,
        path: str = ":memory:",
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        if not callable(resolver):
            raise TypeError("resolver must be callable")
        self._resolver = resolver
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS peer_bindings (
                binding_id TEXT PRIMARY KEY,
                egress_receipt_id TEXT NOT NULL UNIQUE,
                plan_digest TEXT NOT NULL,
                url_sha256 TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                addresses_json TEXT NOT NULL,
                selected_address TEXT NOT NULL,
                dns_sha256 TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                claimed_at INTEGER,
                finished_at INTEGER,
                outcome TEXT,
                peer_address TEXT,
                error_code TEXT
            );
            CREATE TABLE IF NOT EXISTS peer_binding_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                binding_id TEXT NOT NULL,
                egress_receipt_id TEXT NOT NULL,
                plan_digest TEXT NOT NULL,
                url_sha256 TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                addresses_json TEXT NOT NULL,
                selected_address TEXT NOT NULL,
                dns_sha256 TEXT NOT NULL,
                peer_address TEXT,
                outcome TEXT,
                error_code TEXT
            );
            """
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _now(now: int | None) -> int:
        value = int(time.time()) if now is None else now
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PeerBindingContractError("now must be a non-negative integer timestamp")
        return value

    @staticmethod
    def _ttl(ttl_seconds: int) -> int:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= _MAX_TTL_SECONDS
        ):
            raise PeerBindingContractError(
                f"ttl_seconds must be between 1 and {_MAX_TTL_SECONDS}"
            )
        return ttl_seconds

    @staticmethod
    def _error_code(value: str | None, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise PeerBindingContractError("error_code is required")
            return None
        if not isinstance(value, str) or not _ERROR_CODE_RE.fullmatch(value):
            raise PeerBindingContractError("error_code has an invalid format")
        return value

    def _event(
        self,
        row: sqlite3.Row,
        *,
        now: int,
        event_type: str,
        peer_address: str | None = None,
        outcome: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO peer_binding_events (ts,event_type,binding_id,egress_receipt_id,"
            "plan_digest,url_sha256,host,port,addresses_json,selected_address,dns_sha256,"
            "peer_address,outcome,error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now,
                event_type,
                row["binding_id"],
                row["egress_receipt_id"],
                row["plan_digest"],
                row["url_sha256"],
                row["host"],
                row["port"],
                row["addresses_json"],
                row["selected_address"],
                row["dns_sha256"],
                peer_address,
                outcome,
                error_code,
            ),
        )

    @staticmethod
    def _row_binding(row: sqlite3.Row) -> PublicPeerBinding:
        return PublicPeerBinding(
            binding_id=row["binding_id"],
            egress_receipt_id=row["egress_receipt_id"],
            plan_digest=row["plan_digest"],
            url_sha256=row["url_sha256"],
            host=row["host"],
            port=row["port"],
            addresses=tuple(json.loads(row["addresses_json"])),
            selected_address=row["selected_address"],
            dns_sha256=row["dns_sha256"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _matches(
        row: sqlite3.Row,
        binding: PublicPeerBinding,
        plan: EgressPlan,
        receipt: EgressReceipt,
        canonical_url: str,
    ) -> bool:
        return (
            row["binding_id"] == binding.binding_id
            and row["egress_receipt_id"] == receipt.receipt_id == binding.egress_receipt_id
            and row["plan_digest"] == plan.digest == receipt.plan_digest == binding.plan_digest
            and row["url_sha256"] == _url_digest(canonical_url) == binding.url_sha256
            and row["dns_sha256"] == binding.dns_sha256
            and row["selected_address"] == binding.selected_address
        )

    def issue(
        self,
        plan: EgressPlan,
        receipt: EgressReceipt,
        url: str,
        *,
        now: int | None = None,
        ttl_seconds: int = 30,
    ) -> PublicPeerBinding:
        timestamp = self._now(now)
        ttl = self._ttl(ttl_seconds)
        _validate_egress(plan, receipt, timestamp)
        canonical, host, port = _validate_url(plan, url)
        try:
            raw_addresses = tuple(self._resolver(host, port))
        except PeerBindingDenied:
            raise
        except Exception as exc:
            raise PeerBindingDenied("DNS resolution failed") from exc
        addresses = _sort_addresses(raw_addresses)
        selected = addresses[0]
        binding_id = f"pbr_{self._uuid_factory().hex}"
        url_sha256 = _url_digest(canonical)
        dns_sha256 = _dns_digest(host, port, addresses)
        expires_at = min(timestamp + ttl, receipt.expires_at)
        if expires_at <= timestamp:
            raise PeerBindingDenied("egress receipt expires before the binding")

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO peer_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        binding_id,
                        receipt.receipt_id,
                        plan.digest,
                        url_sha256,
                        host,
                        port,
                        json.dumps(addresses, separators=(",", ":")),
                        selected,
                        dns_sha256,
                        timestamp,
                        expires_at,
                        "issued",
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                row = self._conn.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding_id,)
                ).fetchone()
                assert row is not None
                self._event(row, now=timestamp, event_type="issued")
                self._conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._conn.execute("ROLLBACK")
                raise PeerBindingDenied("egress receipt already has a peer binding") from exc
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return PublicPeerBinding(
            binding_id=binding_id,
            egress_receipt_id=receipt.receipt_id,
            plan_digest=plan.digest,
            url_sha256=url_sha256,
            host=host,
            port=port,
            addresses=addresses,
            selected_address=selected,
            dns_sha256=dns_sha256,
            issued_at=timestamp,
            expires_at=expires_at,
        )

    def claim(
        self,
        binding: PublicPeerBinding,
        plan: EgressPlan,
        receipt: EgressReceipt,
        url: str,
        *,
        now: int | None = None,
    ) -> str:
        timestamp = self._now(now)
        _validate_egress(plan, receipt, timestamp)
        canonical, _, _ = _validate_url(plan, url)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding.binding_id,)
                ).fetchone()
                if row is None or not self._matches(row, binding, plan, receipt, canonical):
                    raise PeerBindingDenied("peer binding does not match the request")
                if row["status"] != "issued":
                    raise PeerBindingDenied("peer binding is not claimable")
                if row["expires_at"] <= timestamp:
                    self._conn.execute(
                        "UPDATE peer_bindings SET status='expired', finished_at=? WHERE binding_id=?",
                        (timestamp, binding.binding_id),
                    )
                    self._event(row, now=timestamp, event_type="expired", outcome="blocked", error_code="expired")
                    self._conn.execute("COMMIT")
                    raise PeerBindingDenied("peer binding expired")
                changed = self._conn.execute(
                    "UPDATE peer_bindings SET status='claimed', claimed_at=? "
                    "WHERE binding_id=? AND status='issued'",
                    (timestamp, binding.binding_id),
                ).rowcount
                if changed != 1:
                    raise PeerBindingDenied("peer binding claim lost a race")
                self._event(row, now=timestamp, event_type="claimed")
                self._conn.execute("COMMIT")
            except PeerBindingDenied:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return binding.selected_address

    def complete(
        self,
        binding: PublicPeerBinding,
        plan: EgressPlan,
        receipt: EgressReceipt,
        url: str,
        *,
        outcome: BindingOutcome,
        peer_address: str | None = None,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = self._now(now)
        _validate_egress(plan, receipt, timestamp)
        canonical, _, _ = _validate_url(plan, url)
        if outcome not in {"connected", "failed", "blocked"}:
            raise PeerBindingContractError("outcome is invalid")
        if outcome == "connected":
            code = self._error_code(error_code, required=False)
            if code is not None:
                raise PeerBindingContractError("connected outcome cannot include error_code")
            if peer_address is None:
                raise PeerBindingContractError("connected outcome requires peer_address")
        else:
            code = self._error_code(error_code, required=True)

        normalized_peer: str | None = None
        peer_mismatch = False
        if peer_address is not None:
            try:
                normalized_peer = _public_address(peer_address)
            except PeerBindingDenied:
                peer_mismatch = True
            else:
                peer_mismatch = normalized_peer != binding.selected_address

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding.binding_id,)
                ).fetchone()
                if row is None or not self._matches(row, binding, plan, receipt, canonical):
                    raise PeerBindingDenied("peer binding does not match the request")
                if row["status"] != "claimed":
                    raise PeerBindingDenied("peer binding is not in flight")
                if row["expires_at"] <= timestamp:
                    final_outcome = "blocked"
                    final_code = "expired"
                elif peer_mismatch:
                    final_outcome = "blocked"
                    final_code = "peer_mismatch"
                else:
                    final_outcome = outcome
                    final_code = code
                self._conn.execute(
                    "UPDATE peer_bindings SET status='finished', finished_at=?, outcome=?, "
                    "peer_address=?, error_code=? WHERE binding_id=? AND status='claimed'",
                    (
                        timestamp,
                        final_outcome,
                        normalized_peer,
                        final_code,
                        binding.binding_id,
                    ),
                )
                self._event(
                    row,
                    now=timestamp,
                    event_type="finished",
                    peer_address=normalized_peer,
                    outcome=final_outcome,
                    error_code=final_code,
                )
                self._conn.execute("COMMIT")
            except PeerBindingDenied:
                self._conn.execute("ROLLBACK")
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        if final_outcome == "blocked":
            raise PeerBindingDenied("connected peer did not satisfy the binding")

    def events(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM peer_binding_events ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]
