"""Dormant one-use DNS and connected-peer binding for common research claims.

The ledger consumes only a verified ``ResearchPeerAuthorization`` plus the exact
claim context used to derive it. DNS is injected, no socket is opened here, and
no BrowserHost, CDP, route or provider imports this module.

A transport may count outbound bytes only through ``BoundOutboundByteMeter``
returned after the actual connected peer matches the selected public address.
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

from .research_claim_evidence import DataSharingClaimEvidence
from .research_data_sharing import ResearchSharingIntent
from .research_peer_authorization import (
    ResearchPeerAuthorization,
    ResearchPeerAuthorizationBridge,
    ResearchPeerAuthorizationContractError,
    ResearchPeerAuthorizationDenied,
)
from .research_sharing_boundary import ResearchSharingLease
from .research_sharing_execution import OutboundByteMeter

PEER_BINDING_SCHEMA = "kaliv-research-peer-binding/v1"
PEER_CLAIM_SCHEMA = "kaliv-research-peer-claim/v1"
_MAX_DNS_ANSWERS = 32
_MAX_TTL_SECONDS = 300
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING_ID = re.compile(r"^rpb_[0-9a-f]{32}$")
_AUTHORIZATION_ID = re.compile(r"^rpa_[0-9a-f]{64}$")
_RECEIPT_ID = re.compile(r"^dsr_[a-z0-9._-]{1,96}$")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
BindingOutcome = Literal["completed", "failed", "blocked"]
Resolver = Callable[[str, int], Sequence[str]]


class ResearchCommonPeerContractError(ValueError):
    """The caller supplied malformed peer-binding data or a bad transition."""


class ResearchCommonPeerDenied(PermissionError):
    """Authorization, DNS, expiry, one-use state or connected-peer proof failed."""


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _timestamp(value: int | None) -> int:
    value = int(time.time()) if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchCommonPeerContractError("now must be a non-negative integer timestamp")
    return value


def _ttl(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_TTL_SECONDS
    ):
        raise ResearchCommonPeerContractError(
            f"ttl_seconds must be between 1 and {_MAX_TTL_SECONDS}"
        )
    return value


def _public_address(value: str) -> str:
    if not isinstance(value, str):
        raise ResearchCommonPeerDenied("DNS or transport returned an invalid address")
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ResearchCommonPeerDenied("DNS or transport returned an invalid address") from exc
    if not parsed.is_global:
        raise ResearchCommonPeerDenied("DNS or transport returned a non-public address")
    return parsed.compressed


def _addresses(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ResearchCommonPeerDenied("DNS returned an invalid answer set")
    if not values:
        raise ResearchCommonPeerDenied("DNS returned no addresses")
    if len(values) > _MAX_DNS_ANSWERS:
        raise ResearchCommonPeerDenied("DNS answer budget exceeded")
    normalized = sorted(
        {_public_address(value) for value in values},
        key=lambda value: (
            ipaddress.ip_address(value).version,
            ipaddress.ip_address(value).packed,
        ),
    )
    if not normalized:
        raise ResearchCommonPeerDenied("DNS returned no addresses")
    return tuple(normalized)


def _dns_digest(host: str, port: int, addresses: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical_json({"host": host, "port": port, "addresses": list(addresses)})
    ).hexdigest()


def _error_code(value: str | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ResearchCommonPeerContractError("error_code is required")
        return None
    if not isinstance(value, str) or not _ERROR_CODE.fullmatch(value):
        raise ResearchCommonPeerContractError("error_code has an invalid format")
    return value


@dataclass(frozen=True)
class ResearchCommonPeerBinding:
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
    schema: str = PEER_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PEER_BINDING_SCHEMA:
            raise ResearchCommonPeerContractError("unsupported peer binding schema")
        if not isinstance(self.binding_id, str) or not _BINDING_ID.fullmatch(self.binding_id):
            raise ResearchCommonPeerContractError("binding_id is invalid")
        if not isinstance(self.authorization_id, str) or not _AUTHORIZATION_ID.fullmatch(
            self.authorization_id
        ):
            raise ResearchCommonPeerContractError("authorization_id is invalid")
        if not isinstance(self.claim_receipt_id, str) or not _RECEIPT_ID.fullmatch(
            self.claim_receipt_id
        ):
            raise ResearchCommonPeerContractError("claim_receipt_id is invalid")
        for name, value in (
            ("authorization_digest", self.authorization_digest),
            ("request_digest", self.request_digest),
            ("url_sha256", self.url_sha256),
            ("dns_sha256", self.dns_sha256),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ResearchCommonPeerContractError(
                    f"{name} must be a lowercase SHA-256 digest"
                )
        if not isinstance(self.host, str) or not _HOST.fullmatch(self.host):
            raise ResearchCommonPeerContractError("host is invalid")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ResearchCommonPeerContractError("port is invalid")
        try:
            normalized = _addresses(self.addresses)
            selected = _public_address(self.selected_address)
        except ResearchCommonPeerDenied as exc:
            raise ResearchCommonPeerContractError("binding addresses are invalid") from exc
        if normalized != self.addresses:
            raise ResearchCommonPeerContractError("addresses must be normalized and sorted")
        if selected not in normalized:
            raise ResearchCommonPeerContractError("selected_address is not in addresses")
        if _dns_digest(self.host, self.port, normalized) != self.dns_sha256:
            raise ResearchCommonPeerContractError("dns_sha256 does not match binding")
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= 10_000_000
        ):
            raise ResearchCommonPeerContractError("max_bytes is invalid")
        if (
            isinstance(self.issued_at, bool)
            or not isinstance(self.issued_at, int)
            or self.issued_at < 0
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int)
            or self.expires_at <= self.issued_at
        ):
            raise ResearchCommonPeerContractError("binding timestamps are invalid")

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


@dataclass(frozen=True)
class ResearchCommonPeerClaim:
    binding_id: str
    authorization_digest: str
    selected_address: str
    claimed_at: int
    expires_at: int
    schema: str = PEER_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PEER_CLAIM_SCHEMA:
            raise ResearchCommonPeerContractError("unsupported peer claim schema")
        if not isinstance(self.binding_id, str) or not _BINDING_ID.fullmatch(self.binding_id):
            raise ResearchCommonPeerContractError("claim binding_id is invalid")
        if not isinstance(self.authorization_digest, str) or not _SHA256.fullmatch(
            self.authorization_digest
        ):
            raise ResearchCommonPeerContractError("claim authorization_digest is invalid")
        try:
            _public_address(self.selected_address)
        except ResearchCommonPeerDenied as exc:
            raise ResearchCommonPeerContractError("claim selected_address is invalid") from exc
        if (
            isinstance(self.claimed_at, bool)
            or not isinstance(self.claimed_at, int)
            or self.claimed_at < 0
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int)
            or self.expires_at <= self.claimed_at
        ):
            raise ResearchCommonPeerContractError("claim timestamps are invalid")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "binding_id": self.binding_id,
            "authorization_digest": self.authorization_digest,
            "selected_address": self.selected_address,
            "claimed_at": _iso(self.claimed_at),
            "expires_at": _iso(self.expires_at),
        }


class BoundOutboundByteMeter:
    """Byte meter usable only after exact connected-peer proof."""

    def __init__(
        self,
        meter: OutboundByteMeter,
        *,
        binding_id: str,
        authorization_digest: str,
        peer_address: str,
    ) -> None:
        if not isinstance(meter, OutboundByteMeter):
            raise ResearchCommonPeerContractError("meter must be OutboundByteMeter")
        self._meter = meter
        self.binding_id = binding_id
        self.authorization_digest = authorization_digest
        self.peer_address = _public_address(peer_address)
        self._sealed = False
        self._lock = threading.Lock()

    @property
    def max_bytes(self) -> int:
        return self._meter.max_bytes

    @property
    def bytes_sent(self) -> int:
        return self._meter.bytes_sent

    def record_sent(self, count: int) -> int:
        with self._lock:
            if self._sealed:
                raise ResearchCommonPeerDenied("peer byte meter is sealed")
            return self._meter.record_sent(count)

    def _seal(self) -> None:
        with self._lock:
            self._sealed = True


class ResearchCommonPeerLedger:
    """One-use authorization → DNS → claim → connected peer → terminal audit."""

    def __init__(
        self,
        resolver: Resolver,
        bridge: ResearchPeerAuthorizationBridge,
        path: str = ":memory:",
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        if not callable(resolver):
            raise ResearchCommonPeerContractError("resolver must be callable")
        if not isinstance(bridge, ResearchPeerAuthorizationBridge):
            raise ResearchCommonPeerContractError(
                "bridge must be ResearchPeerAuthorizationBridge"
            )
        self._resolver = resolver
        self._bridge = bridge
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS peer_bindings (
              binding_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL UNIQUE,
              authorization_digest TEXT NOT NULL, claim_receipt_id TEXT NOT NULL,
              request_digest TEXT NOT NULL, url_sha256 TEXT NOT NULL,
              host TEXT NOT NULL, port INTEGER NOT NULL,
              addresses_json TEXT NOT NULL, selected_address TEXT NOT NULL,
              dns_sha256 TEXT NOT NULL, max_bytes INTEGER NOT NULL,
              issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
              status TEXT NOT NULL, claimed_at INTEGER, connected_at INTEGER,
              finished_at INTEGER, peer_address TEXT, bytes_sent INTEGER,
              outcome TEXT, error_code TEXT);
            CREATE TABLE IF NOT EXISTS peer_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
              event_type TEXT NOT NULL, binding_id TEXT NOT NULL,
              authorization_id TEXT NOT NULL, authorization_digest TEXT NOT NULL,
              claim_receipt_id TEXT NOT NULL, request_digest TEXT NOT NULL,
              url_sha256 TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL,
              dns_sha256 TEXT NOT NULL, selected_address TEXT NOT NULL,
              peer_address TEXT, max_bytes INTEGER NOT NULL, bytes_sent INTEGER,
              outcome TEXT, error_code TEXT);
            """
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _verify_context(
        self,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int,
        allow_expired_terminalization: bool = False,
    ) -> None:
        if not isinstance(authorization, ResearchPeerAuthorization):
            raise ResearchCommonPeerContractError(
                "authorization must be ResearchPeerAuthorization"
            )
        verify_now = now
        if allow_expired_terminalization:
            verify_now = min(now, authorization.expires_at - 1)
        try:
            self._bridge.verify(
                authorization,
                evidence,
                lease,
                intent,
                url,
                now=verify_now,
            )
        except ResearchPeerAuthorizationContractError as exc:
            raise ResearchCommonPeerContractError(
                "peer authorization context is malformed"
            ) from exc
        except ResearchPeerAuthorizationDenied as exc:
            raise ResearchCommonPeerDenied(
                "peer authorization is not currently valid"
            ) from exc

    @staticmethod
    def _matches(
        row: sqlite3.Row,
        binding: ResearchCommonPeerBinding,
        authorization: ResearchPeerAuthorization,
    ) -> bool:
        return (
            row["binding_id"] == binding.binding_id
            and row["authorization_id"] == authorization.authorization_id == binding.authorization_id
            and row["authorization_digest"] == authorization.digest == binding.authorization_digest
            and row["claim_receipt_id"] == authorization.claim_receipt_id == binding.claim_receipt_id
            and row["request_digest"] == authorization.request_digest == binding.request_digest
            and row["url_sha256"] == authorization.url_sha256 == binding.url_sha256
            and row["dns_sha256"] == binding.dns_sha256
            and row["selected_address"] == binding.selected_address
            and row["max_bytes"] == authorization.max_bytes == binding.max_bytes
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
        self._db.execute(
            "INSERT INTO peer_events VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                row["max_bytes"],
                bytes_sent,
                outcome,
                error_code,
            ),
        )

    @staticmethod
    def _binding(row: sqlite3.Row) -> ResearchCommonPeerBinding:
        return ResearchCommonPeerBinding(
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
    ) -> ResearchCommonPeerBinding:
        timestamp = _timestamp(now)
        ttl = _ttl(ttl_seconds)
        self._verify_context(authorization, evidence, lease, intent, url, now=timestamp)
        with self._lock:
            existing = self._db.execute(
                "SELECT 1 FROM peer_bindings WHERE authorization_id=?",
                (authorization.authorization_id,),
            ).fetchone()
        if existing is not None:
            raise ResearchCommonPeerDenied("authorization already has a peer binding")
        try:
            raw = self._resolver(authorization.host, authorization.port)
        except ResearchCommonPeerDenied:
            raise
        except Exception as exc:
            raise ResearchCommonPeerDenied("DNS resolution failed") from exc
        addresses = _addresses(raw)
        selected = addresses[0]
        expires_at = min(timestamp + ttl, authorization.expires_at)
        if expires_at <= timestamp:
            raise ResearchCommonPeerDenied("authorization expires before peer binding")
        binding_id = f"rpb_{self._uuid_factory().hex}"
        dns_sha256 = _dns_digest(authorization.host, authorization.port, addresses)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO peer_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        binding_id,
                        authorization.authorization_id,
                        authorization.digest,
                        authorization.claim_receipt_id,
                        authorization.request_digest,
                        authorization.url_sha256,
                        authorization.host,
                        authorization.port,
                        json.dumps(addresses, separators=(",", ":")),
                        selected,
                        dns_sha256,
                        authorization.max_bytes,
                        timestamp,
                        expires_at,
                        "issued",
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                row = self._db.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding_id,)
                ).fetchone()
                assert row is not None
                self._event(row, now=timestamp, event_type="issued")
                self._db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._db.execute("ROLLBACK")
                raise ResearchCommonPeerDenied(
                    "authorization already has a peer binding"
                ) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        return self._binding(row)

    def claim(
        self,
        binding: ResearchCommonPeerBinding,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        meter: OutboundByteMeter,
        *,
        now: int | None = None,
    ) -> ResearchCommonPeerClaim:
        timestamp = _timestamp(now)
        self._verify_context(
            authorization,
            evidence,
            lease,
            intent,
            url,
            now=timestamp,
            allow_expired_terminalization=True,
        )
        if not isinstance(binding, ResearchCommonPeerBinding):
            raise ResearchCommonPeerContractError("binding must be ResearchCommonPeerBinding")
        if not isinstance(meter, OutboundByteMeter):
            raise ResearchCommonPeerContractError("meter must be OutboundByteMeter")
        if meter.max_bytes != authorization.max_bytes or meter.bytes_sent != 0:
            raise ResearchCommonPeerDenied(
                "meter must be unused and match the authorization byte ceiling"
            )
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding.binding_id,)
                ).fetchone()
                if row is None or not self._matches(row, binding, authorization):
                    raise ResearchCommonPeerDenied("peer binding does not match authorization")
                if row["status"] != "issued":
                    raise ResearchCommonPeerDenied("peer binding is not claimable")
                if row["expires_at"] <= timestamp:
                    self._db.execute(
                        "UPDATE peer_bindings SET status='finished',finished_at=?,"
                        "outcome='blocked',error_code='expired',bytes_sent=0 "
                        "WHERE binding_id=?",
                        (timestamp, binding.binding_id),
                    )
                    self._event(
                        row,
                        now=timestamp,
                        event_type="finished",
                        bytes_sent=0,
                        outcome="blocked",
                        error_code="expired",
                    )
                    self._db.execute("COMMIT")
                    raise ResearchCommonPeerDenied("peer binding expired")
                changed = self._db.execute(
                    "UPDATE peer_bindings SET status='claimed',claimed_at=? "
                    "WHERE binding_id=? AND status='issued'",
                    (timestamp, binding.binding_id),
                ).rowcount
                if changed != 1:
                    raise ResearchCommonPeerDenied("peer binding claim lost a race")
                self._event(row, now=timestamp, event_type="claimed")
                self._db.execute("COMMIT")
            except ResearchCommonPeerDenied:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        return ResearchCommonPeerClaim(
            binding_id=binding.binding_id,
            authorization_digest=authorization.digest,
            selected_address=binding.selected_address,
            claimed_at=timestamp,
            expires_at=binding.expires_at,
        )

    def connect(
        self,
        claim: ResearchCommonPeerClaim,
        binding: ResearchCommonPeerBinding,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        meter: OutboundByteMeter,
        peer_address: str,
        *,
        now: int | None = None,
    ) -> BoundOutboundByteMeter:
        timestamp = _timestamp(now)
        self._verify_context(
            authorization,
            evidence,
            lease,
            intent,
            url,
            now=timestamp,
            allow_expired_terminalization=True,
        )
        if not isinstance(claim, ResearchCommonPeerClaim):
            raise ResearchCommonPeerContractError("claim must be ResearchCommonPeerClaim")
        if not isinstance(binding, ResearchCommonPeerBinding):
            raise ResearchCommonPeerContractError("binding must be ResearchCommonPeerBinding")
        if not isinstance(meter, OutboundByteMeter):
            raise ResearchCommonPeerContractError("meter must be OutboundByteMeter")
        if meter.max_bytes != authorization.max_bytes or meter.bytes_sent != 0:
            raise ResearchCommonPeerDenied(
                "meter must remain unused until connected-peer proof succeeds"
            )
        normalized_peer = _public_address(peer_address)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding.binding_id,)
                ).fetchone()
                if (
                    row is None
                    or not self._matches(row, binding, authorization)
                    or claim.binding_id != binding.binding_id
                    or claim.authorization_digest != authorization.digest
                    or claim.selected_address != binding.selected_address
                    or claim.expires_at != binding.expires_at
                ):
                    raise ResearchCommonPeerDenied("peer claim does not match binding")
                if row["status"] != "claimed" or row["claimed_at"] != claim.claimed_at:
                    raise ResearchCommonPeerDenied("peer binding is not awaiting connection")
                if row["expires_at"] <= timestamp:
                    final_code = "expired"
                elif normalized_peer != binding.selected_address:
                    final_code = "peer_mismatch"
                else:
                    final_code = None
                if final_code is not None:
                    self._db.execute(
                        "UPDATE peer_bindings SET status='finished',finished_at=?,"
                        "peer_address=?,outcome='blocked',error_code=?,bytes_sent=0 "
                        "WHERE binding_id=? AND status='claimed'",
                        (timestamp, normalized_peer, final_code, binding.binding_id),
                    )
                    self._event(
                        row,
                        now=timestamp,
                        event_type="finished",
                        peer_address=normalized_peer,
                        bytes_sent=0,
                        outcome="blocked",
                        error_code=final_code,
                    )
                    self._db.execute("COMMIT")
                    raise ResearchCommonPeerDenied("connected peer did not satisfy binding")
                changed = self._db.execute(
                    "UPDATE peer_bindings SET status='connected',connected_at=?,peer_address=? "
                    "WHERE binding_id=? AND status='claimed'",
                    (timestamp, normalized_peer, binding.binding_id),
                ).rowcount
                if changed != 1:
                    raise ResearchCommonPeerDenied("peer connection lost a race")
                self._event(
                    row,
                    now=timestamp,
                    event_type="connected",
                    peer_address=normalized_peer,
                )
                self._db.execute("COMMIT")
            except ResearchCommonPeerDenied:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        return BoundOutboundByteMeter(
            meter,
            binding_id=binding.binding_id,
            authorization_digest=authorization.digest,
            peer_address=normalized_peer,
        )

    def complete(
        self,
        binding: ResearchCommonPeerBinding,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        meter: OutboundByteMeter | BoundOutboundByteMeter,
        *,
        outcome: BindingOutcome,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = _timestamp(now)
        if not isinstance(binding, ResearchCommonPeerBinding):
            raise ResearchCommonPeerContractError("binding must be ResearchCommonPeerBinding")
        if not isinstance(authorization, ResearchPeerAuthorization):
            raise ResearchCommonPeerContractError(
                "authorization must be ResearchPeerAuthorization"
            )
        self._verify_context(
            authorization,
            evidence,
            lease,
            intent,
            url,
            now=timestamp,
            allow_expired_terminalization=True,
        )
        if outcome not in {"completed", "failed", "blocked"}:
            raise ResearchCommonPeerContractError("outcome is invalid")
        code = _error_code(error_code, required=outcome != "completed")
        if outcome == "completed" and code is not None:
            raise ResearchCommonPeerContractError(
                "completed outcome cannot include error_code"
            )
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM peer_bindings WHERE binding_id=?", (binding.binding_id,)
                ).fetchone()
                if row is None or not self._matches(row, binding, authorization):
                    raise ResearchCommonPeerDenied("peer binding does not match authorization")
                status = row["status"]
                if status == "claimed":
                    if not isinstance(meter, OutboundByteMeter) or isinstance(
                        meter, BoundOutboundByteMeter
                    ):
                        raise ResearchCommonPeerContractError(
                            "pre-connect completion requires the original meter"
                        )
                    if meter.bytes_sent != 0 or outcome == "completed":
                        raise ResearchCommonPeerDenied(
                            "pre-connect completion must be zero-byte failure or block"
                        )
                    peer = None
                elif status == "connected":
                    if not isinstance(meter, BoundOutboundByteMeter):
                        raise ResearchCommonPeerContractError(
                            "connected completion requires BoundOutboundByteMeter"
                        )
                    if (
                        meter.binding_id != binding.binding_id
                        or meter.authorization_digest != authorization.digest
                        or meter.peer_address != row["peer_address"]
                    ):
                        raise ResearchCommonPeerDenied(
                            "bound meter does not match connected peer"
                        )
                    peer = meter.peer_address
                else:
                    raise ResearchCommonPeerDenied("peer binding is not completable")
                bytes_sent = meter.bytes_sent
                if bytes_sent > binding.max_bytes:
                    raise ResearchCommonPeerDenied("meter exceeds binding byte ceiling")
                final_outcome = outcome
                final_code = code
                if row["expires_at"] <= timestamp:
                    final_outcome = "blocked"
                    final_code = "expired"
                changed = self._db.execute(
                    "UPDATE peer_bindings SET status='finished',finished_at=?,bytes_sent=?,"
                    "outcome=?,error_code=? WHERE binding_id=? AND status=?",
                    (
                        timestamp,
                        bytes_sent,
                        final_outcome,
                        final_code,
                        binding.binding_id,
                        status,
                    ),
                ).rowcount
                if changed != 1:
                    raise ResearchCommonPeerDenied("peer completion lost a race")
                self._event(
                    row,
                    now=timestamp,
                    event_type="finished",
                    peer_address=peer,
                    bytes_sent=bytes_sent,
                    outcome=final_outcome,
                    error_code=final_code,
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        if isinstance(meter, BoundOutboundByteMeter):
            meter._seal()
        if final_outcome == "blocked" and final_code == "expired":
            raise ResearchCommonPeerDenied("peer binding expired before completion")

    def events(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM peer_events ORDER BY id").fetchall()
        return [dict(row) for row in rows]
