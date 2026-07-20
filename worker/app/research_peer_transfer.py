"""Dormant one-use DNS and connected-peer binding for common research claims.

The module performs no socket, browser, CDP, provider or route I/O. A caller
injects a resolver, derives one short-lived binding from an exact
``ResearchPeerAuthorization``, claims it once, connects only to the selected
public address, reports the actual connected peer and records confirmed outbound
progress through a claim-bound ``OutboundByteMeter``.
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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from .research_claim_evidence import DataSharingClaimEvidence
from .research_data_sharing import ResearchSharingIntent
from .research_peer_authorization import (
    ResearchPeerAuthorization,
    ResearchPeerAuthorizationBridge,
    ResearchPeerAuthorizationDenied,
)
from .research_sharing_boundary import ResearchSharingLease
from .research_sharing_execution import OutboundByteMeter

PEER_TRANSFER_SCHEMA = "kaliv-research-peer-transfer/v1"
_MAX_DNS_ANSWERS = 32
_MAX_TTL_SECONDS = 300
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
Resolver = Callable[[str, int], Sequence[str]]
PeerOutcome = Literal["connected", "failed", "blocked"]
_TRANSFER_TOKEN = object()


class ResearchPeerTransferContractError(ValueError):
    """A peer-transfer input or state object is malformed."""


class ResearchPeerTransferDenied(PermissionError):
    """The common claim, DNS answer, one-use state or connected peer was refused."""


def _canonical_json(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchPeerTransferContractError(
            f"{name} must be a non-negative integer timestamp"
        )
    return value


def _public_address(value: str) -> str:
    if not isinstance(value, str):
        raise ResearchPeerTransferDenied("DNS or transport returned an invalid address")
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ResearchPeerTransferDenied(
            "DNS or transport returned an invalid address"
        ) from exc
    if not parsed.is_global:
        raise ResearchPeerTransferDenied(
            "DNS or transport returned a non-public address"
        )
    return parsed.compressed


def _addresses(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ResearchPeerTransferDenied("DNS result must be an address sequence")
    if not values:
        raise ResearchPeerTransferDenied("DNS returned no addresses")
    if len(values) > _MAX_DNS_ANSWERS:
        raise ResearchPeerTransferDenied("DNS answer budget exceeded")
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
        raise ResearchPeerTransferDenied("DNS returned no addresses")
    return tuple(normalized)


def _dns_digest(host: str, port: int, addresses: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "host": host,
                "port": port,
                "addresses": list(addresses),
            }
        )
    ).hexdigest()


@dataclass(frozen=True)
class ResearchPeerBinding:
    """One deterministic target selected from a short-lived public DNS answer."""

    binding_id: str
    authorization_id: str
    authorization_digest: str
    claim_receipt_id: str
    request_digest: str
    url_sha256: str
    host: str
    port: int
    addresses: tuple[str, ...]
    selected_address: str
    dns_sha256: str
    max_bytes: int
    issued_at: int
    expires_at: int
    schema: str = PEER_TRANSFER_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PEER_TRANSFER_SCHEMA:
            raise ResearchPeerTransferContractError(
                "unsupported peer-transfer schema"
            )
        if not isinstance(self.binding_id, str) or not self.binding_id.startswith(
            "rpt_"
        ):
            raise ResearchPeerTransferContractError("binding_id is invalid")
        if not isinstance(
            self.authorization_id, str
        ) or not self.authorization_id.startswith("rpa_"):
            raise ResearchPeerTransferContractError("authorization_id is invalid")
        if not isinstance(
            self.claim_receipt_id, str
        ) or not self.claim_receipt_id.startswith("dsr_"):
            raise ResearchPeerTransferContractError("claim_receipt_id is invalid")
        for name, value in (
            ("authorization_digest", self.authorization_digest),
            ("request_digest", self.request_digest),
            ("url_sha256", self.url_sha256),
            ("dns_sha256", self.dns_sha256),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ResearchPeerTransferContractError(
                    f"{name} must be a lowercase SHA-256 digest"
                )
        if self.authorization_id != f"rpa_{self.authorization_digest}":
            raise ResearchPeerTransferContractError(
                "authorization_id does not match authorization_digest"
            )
        if (
            not isinstance(self.host, str)
            or not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?",
                self.host,
            )
        ):
            raise ResearchPeerTransferContractError("host is invalid")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ResearchPeerTransferContractError("port is invalid")
        try:
            normalized = _addresses(self.addresses)
            selected = _public_address(self.selected_address)
        except ResearchPeerTransferDenied as exc:
            raise ResearchPeerTransferContractError(
                "binding addresses are invalid"
            ) from exc
        if normalized != self.addresses:
            raise ResearchPeerTransferContractError(
                "addresses must be normalized and sorted"
            )
        if selected not in normalized:
            raise ResearchPeerTransferContractError(
                "selected_address must be one of the DNS answers"
            )
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= 10_000_000
        ):
            raise ResearchPeerTransferContractError("max_bytes is invalid")
        _timestamp(self.issued_at, "issued_at")
        _timestamp(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ResearchPeerTransferContractError(
                "binding expiry must follow issue time"
            )
        if _dns_digest(self.host, self.port, normalized) != self.dns_sha256:
            raise ResearchPeerTransferContractError(
                "dns_sha256 does not match the binding"
            )

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "binding_id": self.binding_id,
            "authorization_id": self.authorization_id,
            "authorization_digest": self.authorization_digest,
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "addresses": list(self.addresses),
            "selected_address": self.selected_address,
            "dns_sha256": self.dns_sha256,
            "max_bytes": self.max_bytes,
            "issued_at": _iso(self.issued_at),
            "expires_at": _iso(self.expires_at),
        }


class ResearchPeerTransfer:
    """Claim-bound selected peer and byte meter, constructible only by the ledger."""

    def __init__(
        self,
        binding: ResearchPeerBinding,
        *,
        token: object,
    ) -> None:
        if token is not _TRANSFER_TOKEN:
            raise ResearchPeerTransferContractError(
                "peer transfers must be created by ResearchPeerTransferLedger"
            )
        self.binding = binding
        self._meter = OutboundByteMeter(binding.max_bytes)
        self._lock = threading.Lock()
        self._active = True

    @property
    def selected_address(self) -> str:
        return self.binding.selected_address

    @property
    def bytes_sent(self) -> int:
        return self._meter.bytes_sent

    def record_sent(self, count: int) -> int:
        with self._lock:
            if not self._active:
                raise ResearchPeerTransferDenied("peer transfer is already terminal")
            return self._meter.record_sent(count)

    def _seal(self) -> int:
        with self._lock:
            if not self._active:
                raise ResearchPeerTransferDenied("peer transfer is already terminal")
            self._active = False
            return self._meter.bytes_sent


class ResearchPeerTransferLedger:
    """SQLite-backed one-use DNS, peer and measured-byte state machine."""

    def __init__(
        self,
        bridge: ResearchPeerAuthorizationBridge,
        resolver: Resolver,
        path: str = ":memory:",
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        if not isinstance(bridge, ResearchPeerAuthorizationBridge):
            raise ResearchPeerTransferContractError(
                "ledger requires ResearchPeerAuthorizationBridge"
            )
        if not callable(resolver):
            raise ResearchPeerTransferContractError("resolver must be callable")
        self._bridge = bridge
        self._resolver = resolver
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_peer_transfers (
                binding_id TEXT PRIMARY KEY,
                authorization_id TEXT NOT NULL UNIQUE,
                authorization_digest TEXT NOT NULL,
                claim_receipt_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                url_sha256 TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                addresses_json TEXT NOT NULL,
                selected_address TEXT NOT NULL,
                dns_sha256 TEXT NOT NULL,
                max_bytes INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                claimed_at INTEGER,
                finished_at INTEGER,
                outcome TEXT,
                peer_address TEXT,
                bytes_sent INTEGER,
                error_code TEXT
            );
            CREATE TABLE IF NOT EXISTS research_peer_transfer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                binding_id TEXT NOT NULL,
                authorization_id TEXT NOT NULL,
                authorization_digest TEXT NOT NULL,
                claim_receipt_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                url_sha256 TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                dns_sha256 TEXT NOT NULL,
                selected_address TEXT NOT NULL,
                peer_address TEXT,
                bytes_sent INTEGER,
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
        return _timestamp(value, "now")

    @staticmethod
    def _ttl(ttl_seconds: int) -> int:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= _MAX_TTL_SECONDS
        ):
            raise ResearchPeerTransferContractError(
                f"ttl_seconds must be between 1 and {_MAX_TTL_SECONDS}"
            )
        return ttl_seconds

    @staticmethod
    def _error_code(value: str | None, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise ResearchPeerTransferContractError("error_code is required")
            return None
        if not isinstance(value, str) or not _ERROR_CODE.fullmatch(value):
            raise ResearchPeerTransferContractError(
                "error_code has an invalid format"
            )
        return value

    def _verify(
        self,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int,
    ) -> None:
        try:
            self._bridge.verify(
                authorization,
                evidence,
                lease,
                intent,
                url,
                now=now,
            )
        except ResearchPeerAuthorizationDenied as exc:
            raise ResearchPeerTransferDenied(
                "peer authorization is not active for this exact request"
            ) from exc

    @staticmethod
    def _row_binding(row: sqlite3.Row) -> ResearchPeerBinding:
        return ResearchPeerBinding(
            binding_id=row["binding_id"],
            authorization_id=row["authorization_id"],
            authorization_digest=row["authorization_digest"],
            claim_receipt_id=row["claim_receipt_id"],
            request_digest=row["request_digest"],
            url_sha256=row["url_sha256"],
            host=row["host"],
            port=row["port"],
            addresses=tuple(json.loads(row["addresses_json"])),
            selected_address=row["selected_address"],
            dns_sha256=row["dns_sha256"],
            max_bytes=row["max_bytes"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _matches(
        row: sqlite3.Row,
        binding: ResearchPeerBinding,
        authorization: ResearchPeerAuthorization,
    ) -> bool:
        return (
            row["binding_id"] == binding.binding_id
            and row["authorization_id"]
            == authorization.authorization_id
            == binding.authorization_id
            and row["authorization_digest"]
            == authorization.digest
            == binding.authorization_digest
            and row["claim_receipt_id"]
            == authorization.claim_receipt_id
            == binding.claim_receipt_id
            and row["request_digest"]
            == authorization.request_digest
            == binding.request_digest
            and row["url_sha256"] == authorization.url_sha256 == binding.url_sha256
            and row["host"] == authorization.host == binding.host
            and row["port"] == authorization.port == binding.port
            and row["max_bytes"] == authorization.max_bytes == binding.max_bytes
            and row["dns_sha256"] == binding.dns_sha256
            and row["selected_address"] == binding.selected_address
        )

    def _event(
        self,
        row: sqlite3.Row,
        *,
        now: int,
        event_type: str,
        peer_address: str | None = None,
        bytes_sent: int | None = None,
        outcome: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO research_peer_transfer_events "
            "(ts,event_type,binding_id,authorization_id,authorization_digest,"
            "claim_receipt_id,request_digest,url_sha256,host,port,dns_sha256,"
            "selected_address,peer_address,bytes_sent,outcome,error_code) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now,
                event_type,
                row["binding_id"],
                row["authorization_id"],
                row["authorization_digest"],
                row["claim_receipt_id"],
                row["request_digest"],
                row["url_sha256"],
                row["host"],
                row["port"],
                row["dns_sha256"],
                row["selected_address"],
                peer_address,
                bytes_sent,
                outcome,
                error_code,
            ),
        )

    def issue(
        self,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int | None = None,
        ttl_seconds: int = 30,
    ) -> ResearchPeerBinding:
        timestamp = self._now(now)
        ttl = self._ttl(ttl_seconds)
        self._verify(
            authorization,
            evidence,
            lease,
            intent,
            url,
            now=timestamp,
        )
        try:
            raw_addresses = tuple(
                self._resolver(authorization.host, authorization.port)
            )
        except ResearchPeerTransferDenied:
            raise
        except Exception as exc:
            raise ResearchPeerTransferDenied("DNS resolution failed") from exc
        addresses = _addresses(raw_addresses)
        selected = addresses[0]
        dns_sha256 = _dns_digest(
            authorization.host,
            authorization.port,
            addresses,
        )
        expires_at = min(timestamp + ttl, authorization.expires_at)
        if expires_at <= timestamp:
            raise ResearchPeerTransferDenied(
                "peer authorization expires before the DNS binding"
            )
        binding = ResearchPeerBinding(
            binding_id=f"rpt_{self._uuid_factory().hex}",
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.digest,
            claim_receipt_id=authorization.claim_receipt_id,
            request_digest=authorization.request_digest,
            url_sha256=authorization.url_sha256,
            host=authorization.host,
            port=authorization.port,
            addresses=addresses,
            selected_address=selected,
            dns_sha256=dns_sha256,
            max_bytes=authorization.max_bytes,
            issued_at=timestamp,
            expires_at=expires_at,
        )

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO research_peer_transfers VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        binding.binding_id,
                        binding.authorization_id,
                        binding.authorization_digest,
                        binding.claim_receipt_id,
                        binding.request_digest,
                        binding.url_sha256,
                        binding.host,
                        binding.port,
                        json.dumps(binding.addresses, separators=(",", ":")),
                        binding.selected_address,
                        binding.dns_sha256,
                        binding.max_bytes,
                        binding.issued_at,
                        binding.expires_at,
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
                    "SELECT * FROM research_peer_transfers WHERE binding_id=?",
                    (binding.binding_id,),
                ).fetchone()
                assert row is not None
                self._event(row, now=timestamp, event_type="issued")
                self._conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._conn.execute("ROLLBACK")
                raise ResearchPeerTransferDenied(
                    "peer authorization already has a DNS binding"
                ) from exc
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return binding

    def claim(
        self,
        binding: ResearchPeerBinding,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int | None = None,
    ) -> ResearchPeerTransfer:
        if not isinstance(binding, ResearchPeerBinding):
            raise ResearchPeerTransferContractError(
                "binding must be a ResearchPeerBinding"
            )
        timestamp = self._now(now)
        self._verify(
            authorization,
            evidence,
            lease,
            intent,
            url,
            now=timestamp,
        )
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM research_peer_transfers WHERE binding_id=?",
                    (binding.binding_id,),
                ).fetchone()
                if row is None or not self._matches(
                    row,
                    binding,
                    authorization,
                ):
                    raise ResearchPeerTransferDenied(
                        "peer binding does not match the authorization"
                    )
                if row["status"] != "issued":
                    raise ResearchPeerTransferDenied(
                        "peer binding is not claimable"
                    )
                if row["expires_at"] <= timestamp:
                    self._conn.execute(
                        "UPDATE research_peer_transfers "
                        "SET status='expired', finished_at=?, outcome='blocked', "
                        "bytes_sent=0, error_code='expired' WHERE binding_id=?",
                        (timestamp, binding.binding_id),
                    )
                    self._event(
                        row,
                        now=timestamp,
                        event_type="expired",
                        bytes_sent=0,
                        outcome="blocked",
                        error_code="expired",
                    )
                    self._conn.execute("COMMIT")
                    raise ResearchPeerTransferDenied("peer binding expired")
                changed = self._conn.execute(
                    "UPDATE research_peer_transfers "
                    "SET status='claimed', claimed_at=? "
                    "WHERE binding_id=? AND status='issued'",
                    (timestamp, binding.binding_id),
                ).rowcount
                if changed != 1:
                    raise ResearchPeerTransferDenied(
                        "peer binding claim lost a race"
                    )
                self._event(row, now=timestamp, event_type="claimed")
                self._conn.execute("COMMIT")
            except ResearchPeerTransferDenied:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return ResearchPeerTransfer(binding, token=_TRANSFER_TOKEN)

    def complete(
        self,
        transfer: ResearchPeerTransfer,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        outcome: PeerOutcome,
        peer_address: str | None = None,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        if not isinstance(transfer, ResearchPeerTransfer):
            raise ResearchPeerTransferContractError(
                "transfer must be a ResearchPeerTransfer"
            )
        timestamp = self._now(now)
        if outcome not in {"connected", "failed", "blocked"}:
            raise ResearchPeerTransferContractError("outcome is invalid")
        if outcome == "connected":
            code = self._error_code(error_code, required=False)
            if code is not None:
                raise ResearchPeerTransferContractError(
                    "connected outcome cannot include error_code"
                )
            if peer_address is None:
                raise ResearchPeerTransferContractError(
                    "connected outcome requires peer_address"
                )
        else:
            code = self._error_code(error_code, required=True)

        context_active = True
        try:
            self._verify(
                authorization,
                evidence,
                lease,
                intent,
                url,
                now=timestamp,
            )
        except ResearchPeerTransferDenied:
            context_active = False

        normalized_peer: str | None = None
        peer_mismatch = False
        if peer_address is not None:
            try:
                normalized_peer = _public_address(peer_address)
            except ResearchPeerTransferDenied:
                peer_mismatch = True
            else:
                peer_mismatch = (
                    normalized_peer != transfer.binding.selected_address
                )

        bytes_sent = transfer._seal()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM research_peer_transfers WHERE binding_id=?",
                    (transfer.binding.binding_id,),
                ).fetchone()
                if row is None or not self._matches(
                    row,
                    transfer.binding,
                    authorization,
                ):
                    raise ResearchPeerTransferDenied(
                        "peer transfer does not match the authorization"
                    )
                if row["status"] != "claimed":
                    raise ResearchPeerTransferDenied(
                        "peer transfer is not in flight"
                    )
                if not context_active:
                    final_outcome = "blocked"
                    final_code = "claim_inactive"
                elif row["expires_at"] <= timestamp:
                    final_outcome = "blocked"
                    final_code = "expired"
                elif peer_mismatch:
                    final_outcome = "blocked"
                    final_code = "peer_mismatch"
                else:
                    final_outcome = outcome
                    final_code = code
                changed = self._conn.execute(
                    "UPDATE research_peer_transfers "
                    "SET status='finished', finished_at=?, outcome=?, "
                    "peer_address=?, bytes_sent=?, error_code=? "
                    "WHERE binding_id=? AND status='claimed'",
                    (
                        timestamp,
                        final_outcome,
                        normalized_peer,
                        bytes_sent,
                        final_code,
                        transfer.binding.binding_id,
                    ),
                ).rowcount
                if changed != 1:
                    raise ResearchPeerTransferDenied(
                        "peer transfer completion lost a race"
                    )
                self._event(
                    row,
                    now=timestamp,
                    event_type="finished",
                    peer_address=normalized_peer,
                    bytes_sent=bytes_sent,
                    outcome=final_outcome,
                    error_code=final_code,
                )
                self._conn.execute("COMMIT")
            except ResearchPeerTransferDenied:
                self._conn.execute("ROLLBACK")
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        if final_outcome == "blocked":
            raise ResearchPeerTransferDenied(
                "connected peer or active claim did not satisfy the binding"
            )

    def events(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM research_peer_transfer_events ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]
