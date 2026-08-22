"""Dormant authority contract for T-038 RigGate/Home Assistant read-first pilot.

The contract lands before any network client, ToolGate registration or worker
mount. It owns the exact durable scope, revocation, freshness semantics,
side-effect-free wake/control previews, privacy-minimized audit evidence and the
T-032 data-sharing request binding.

Important invariants:

* scope names explicit rig ids and Home Assistant entity ids;
* v1 has no executable wake/control operation, only preview operations;
* stale or unavailable source data normalizes to ``unknown`` even when the last
  observed source state happened to say ``ready``;
* every observation carries source identity, check timestamp and freshness;
* audit records which scoped object was read, never the sensor value itself;
* no route, tool, environment, socket, HTTP client or production activation is
  present in this module.
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
from typing import Literal

from .data_sharing import DataSharingRequest

SCOPE_SCHEMA = "kaliv-home-rig-scope/v1"
GRANT_SCHEMA = "kaliv-home-rig-grant/v1"
OBSERVATION_SCHEMA = "kaliv-home-rig-observation/v1"
PREVIEW_SCHEMA = "kaliv-home-rig-preview/v1"
PRODUCTION_ACTIVATION = False

TargetKind = Literal["rig", "entity"]
Operation = Literal[
    "rig_health",
    "rig_power_readiness",
    "entity_state",
    "wake_preview",
    "control_preview",
]
Freshness = Literal["fresh", "stale", "unavailable"]
AuditOutcome = Literal["executed", "blocked", "error"]

_OPERATIONS = {
    "rig_health",
    "rig_power_readiness",
    "entity_state",
    "wake_preview",
    "control_preview",
}
_RIG_OPERATIONS = {"rig_health", "rig_power_readiness", "wake_preview"}
_ENTITY_OPERATIONS = {"entity_state", "control_preview"}
_RIG_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_GRANT_ID = re.compile(r"^hrg_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DETAIL = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+%-]{0,255}$")
_MAX_SCOPE_OBJECTS = 100
_MAX_FRESHNESS_SECONDS = 24 * 60 * 60


class HomeRigContractError(ValueError):
    """The T-038 closed contract is malformed."""


class HomeRigDenied(PermissionError):
    """A request is outside the exact active T-038 scope."""


def _now(value: int | None) -> int:
    resolved = int(time.time()) if value is None else value
    if isinstance(resolved, bool) or not isinstance(resolved, int) or resolved < 0:
        raise HomeRigContractError("time must be a non-negative integer")
    return resolved


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _rig_id(value: str) -> str:
    if not isinstance(value, str):
        raise HomeRigContractError("rig_id must be a string")
    normalized = value.strip().lower()
    if not _RIG_ID.fullmatch(normalized):
        raise HomeRigContractError("rig_id must be a stable slug")
    return normalized


def _entity_id(value: str) -> str:
    if not isinstance(value, str):
        raise HomeRigContractError("entity_id must be a string")
    normalized = value.strip().lower()
    if not _ENTITY_ID.fullmatch(normalized) or len(normalized) > 255:
        raise HomeRigContractError("entity_id must be an exact Home Assistant entity id")
    return normalized


def _operation(value: str) -> Operation:
    if value not in _OPERATIONS:
        raise HomeRigContractError("unsupported home/rig operation")
    return value  # type: ignore[return-value]


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _stable_tuple(values: tuple[str, ...], validator, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise HomeRigContractError(f"{name} must be a tuple")
    normalized = tuple(sorted({validator(value) for value in values}))
    if len(normalized) != len(values):
        raise HomeRigContractError(f"{name} contains duplicates")
    if len(normalized) > _MAX_SCOPE_OBJECTS:
        raise HomeRigContractError(f"{name} exceeds {_MAX_SCOPE_OBJECTS} objects")
    return normalized


_CAPABILITY_ID = {
    "rig": "tool:riggate_read",
    "entity": "tool:home_assistant_read",
}


@dataclass(frozen=True)
class HomeRigScope:
    rig_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    operations: tuple[Operation, ...] = ()
    schema: str = SCOPE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != SCOPE_SCHEMA:
            raise HomeRigContractError("unsupported home/rig scope schema")
        if self.production_activation is not False:
            raise HomeRigContractError("production activation must remain false")
        rigs = _stable_tuple(self.rig_ids, _rig_id, "rig_ids")
        entities = _stable_tuple(self.entity_ids, _entity_id, "entity_ids")
        if not rigs and not entities:
            raise HomeRigContractError("scope requires at least one rig or entity")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise HomeRigContractError("scope requires explicit operations")
        operations = tuple(sorted({_operation(value) for value in self.operations}))
        if len(operations) != len(self.operations):
            raise HomeRigContractError("scope operations contain duplicates")
        if _RIG_OPERATIONS.intersection(operations) and not rigs:
            raise HomeRigContractError("rig operations require explicit rig_ids")
        if _ENTITY_OPERATIONS.intersection(operations) and not entities:
            raise HomeRigContractError("entity operations require explicit entity_ids")
        object.__setattr__(self, "rig_ids", rigs)
        object.__setattr__(self, "entity_ids", entities)
        object.__setattr__(self, "operations", operations)

    def digest_payload(self) -> dict:
        return {
            "schema": self.schema,
            "rig_ids": list(self.rig_ids),
            "entity_ids": list(self.entity_ids),
            "operations": list(self.operations),
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.digest_payload())).hexdigest()

    def allows(self, *, target_kind: TargetKind, target_id: str, operation: str) -> bool:
        operation = _operation(operation)
        if target_kind == "rig":
            target = _rig_id(target_id)
            return operation in _RIG_OPERATIONS and operation in self.operations and target in self.rig_ids
        if target_kind == "entity":
            target = _entity_id(target_id)
            return operation in _ENTITY_OPERATIONS and operation in self.operations and target in self.entity_ids
        raise HomeRigContractError("target_kind must be rig or entity")

    def to_dict(self) -> dict:
        return {
            **self.digest_payload(),
            "scope_sha256": self.digest,
            "capability_ids": [
                value
                for kind, value in _CAPABILITY_ID.items()
                if (kind == "rig" and self.rig_ids) or (kind == "entity" and self.entity_ids)
            ],
        }


@dataclass(frozen=True)
class HomeRigGrant:
    grant_id: str
    scope: HomeRigScope
    created_at: int
    created_by: str
    revoked_at: int | None = None
    revoked_by: str | None = None
    schema: str = GRANT_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != GRANT_SCHEMA:
            raise HomeRigContractError("unsupported home/rig grant schema")
        if self.production_activation is not False:
            raise HomeRigContractError("production activation must remain false")
        if not isinstance(self.grant_id, str) or not _GRANT_ID.fullmatch(self.grant_id):
            raise HomeRigContractError("grant_id has invalid format")
        if not isinstance(self.scope, HomeRigScope):
            raise HomeRigContractError("grant requires HomeRigScope")
        _now(self.created_at)
        if not isinstance(self.created_by, str) or not self.created_by.strip() or len(self.created_by) > 120:
            raise HomeRigContractError("created_by must identify the operator")
        if self.revoked_at is not None:
            _now(self.revoked_at)
            if self.revoked_at < self.created_at:
                raise HomeRigContractError("grant revoke time predates creation")
            if not isinstance(self.revoked_by, str) or not self.revoked_by.strip():
                raise HomeRigContractError("revoked grant requires revoked_by")
        elif self.revoked_by is not None:
            raise HomeRigContractError("active grant cannot carry revoked_by")

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope": self.scope.to_dict(),
            "status": "active" if self.active else "revoked",
            "created_at": _iso(self.created_at),
            "created_by": self.created_by,
            "revoked_at": _iso(self.revoked_at) if self.revoked_at is not None else None,
            "revoked_by": self.revoked_by,
            "production_activation": False,
        }


class HomeRigGrantStore:
    """Durable exact T-038 authority with compare-before-revoke semantics."""

    def __init__(self, path: str = ":memory:", *, uuid_factory=uuid.uuid4) -> None:
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS home_rig_grants (
                grant_id TEXT PRIMARY KEY,
                scope_json TEXT NOT NULL,
                scope_sha256 TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                created_by TEXT NOT NULL,
                revoked_at INTEGER,
                revoked_by TEXT
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create(self, scope: HomeRigScope, *, actor: str, now: int | None = None) -> HomeRigGrant:
        if not isinstance(scope, HomeRigScope):
            raise HomeRigContractError("grant creation requires HomeRigScope")
        now = _now(now)
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise HomeRigContractError("grant actor is invalid")
        grant_id = f"hrg_{self._uuid_factory().hex}"
        payload = json.dumps(scope.digest_payload(), sort_keys=True, separators=(",", ":"))
        with self._lock:
            self._db.execute(
                "INSERT INTO home_rig_grants VALUES (?,?,?,?,?,?,NULL)",
                (grant_id, payload, scope.digest, now, actor.strip(), None),
            )
            self._db.commit()
        grant = self.get(grant_id)
        assert grant is not None
        return grant

    @staticmethod
    def _scope(raw: str) -> HomeRigScope:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HomeRigContractError("stored home/rig scope is invalid JSON") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema", "rig_ids", "entity_ids", "operations", "production_activation"
        }:
            raise HomeRigContractError("stored home/rig scope shape is invalid")
        if value.get("production_activation") is not False:
            raise HomeRigContractError("stored scope activation drifted")
        return HomeRigScope(
            rig_ids=tuple(value["rig_ids"]),
            entity_ids=tuple(value["entity_ids"]),
            operations=tuple(value["operations"]),
            schema=value["schema"],
        )

    @classmethod
    def _grant(cls, row: sqlite3.Row) -> HomeRigGrant:
        scope = cls._scope(row["scope_json"])
        if scope.digest != row["scope_sha256"]:
            raise HomeRigContractError("stored home/rig scope digest mismatch")
        return HomeRigGrant(
            grant_id=row["grant_id"],
            scope=scope,
            created_at=row["created_at"],
            created_by=row["created_by"],
            revoked_at=row["revoked_at"],
            revoked_by=row["revoked_by"],
        )

    def get(self, grant_id: str) -> HomeRigGrant | None:
        if not isinstance(grant_id, str) or not _GRANT_ID.fullmatch(grant_id):
            raise HomeRigContractError("grant_id has invalid format")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM home_rig_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
        return self._grant(row) if row is not None else None

    def list_grants(self, *, include_revoked: bool = False) -> tuple[HomeRigGrant, ...]:
        where = "" if include_revoked else " WHERE revoked_at IS NULL"
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM home_rig_grants{where} ORDER BY created_at, grant_id"
            ).fetchall()
        return tuple(self._grant(row) for row in rows)

    def authorize(
        self,
        grant_id: str,
        *,
        target_kind: TargetKind,
        target_id: str,
        operation: str,
    ) -> HomeRigGrant:
        grant = self.get(grant_id)
        if grant is None or not grant.active:
            raise HomeRigDenied("home/rig grant is missing or revoked")
        if not grant.scope.allows(
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,
        ):
            raise HomeRigDenied("home/rig request is outside exact active scope")
        return grant

    def revoke(
        self,
        grant_id: str,
        *,
        expected_scope_sha256: str,
        actor: str,
        now: int | None = None,
    ) -> HomeRigGrant:
        if not isinstance(expected_scope_sha256, str) or not _SHA256.fullmatch(expected_scope_sha256):
            raise HomeRigContractError("expected_scope_sha256 must be lowercase SHA-256")
        now = _now(now)
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise HomeRigContractError("revoke actor is invalid")
        with self._lock:
            current = self.get(grant_id)
            if current is None:
                raise HomeRigDenied("unknown home/rig grant")
            if current.scope.digest != expected_scope_sha256:
                raise HomeRigDenied("home/rig scope changed before revoke")
            if current.active:
                self._db.execute(
                    "UPDATE home_rig_grants SET revoked_at=?, revoked_by=? "
                    "WHERE grant_id=? AND revoked_at IS NULL",
                    (now, actor.strip(), grant_id),
                )
                self._db.commit()
            updated = self.get(grant_id)
        assert updated is not None
        return updated


@dataclass(frozen=True)
class HomeRigObservation:
    source: Literal["riggate", "home_assistant"]
    target_kind: TargetKind
    target_id: str
    operation: Literal["rig_health", "rig_power_readiness", "entity_state"]
    state: str
    checked_at: int
    observed_at: int | None
    freshness: Freshness
    freshness_seconds: int | None
    max_freshness_seconds: int
    schema: str = OBSERVATION_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != OBSERVATION_SCHEMA:
            raise HomeRigContractError("unsupported observation schema")
        if self.production_activation is not False:
            raise HomeRigContractError("production activation must remain false")
        if self.source not in {"riggate", "home_assistant"}:
            raise HomeRigContractError("observation source is invalid")
        if self.target_kind == "rig":
            target_id = _rig_id(self.target_id)
            if self.source != "riggate" or self.operation not in {"rig_health", "rig_power_readiness"}:
                raise HomeRigContractError("rig observations must come from RigGate")
        elif self.target_kind == "entity":
            target_id = _entity_id(self.target_id)
            if self.source != "home_assistant" or self.operation != "entity_state":
                raise HomeRigContractError("entity observations must come from Home Assistant")
        else:
            raise HomeRigContractError("observation target_kind is invalid")
        checked_at = _now(self.checked_at)
        if (
            isinstance(self.max_freshness_seconds, bool)
            or not isinstance(self.max_freshness_seconds, int)
            or not 1 <= self.max_freshness_seconds <= _MAX_FRESHNESS_SECONDS
        ):
            raise HomeRigContractError("max freshness is invalid")
        if self.freshness not in {"fresh", "stale", "unavailable"}:
            raise HomeRigContractError("observation freshness is invalid")
        if self.freshness == "unavailable":
            if self.observed_at is not None or self.freshness_seconds is not None or self.state != "unknown":
                raise HomeRigContractError("unavailable observations must be unknown without source timestamp")
        else:
            if self.observed_at is None:
                raise HomeRigContractError("available observation requires observed_at")
            observed_at = _now(self.observed_at)
            if observed_at > checked_at:
                raise HomeRigContractError("source observation cannot be from the future")
            expected_age = checked_at - observed_at
            if self.freshness_seconds != expected_age:
                raise HomeRigContractError("freshness_seconds does not match timestamps")
            if self.freshness == "fresh":
                if expected_age > self.max_freshness_seconds:
                    raise HomeRigContractError("fresh observation exceeds freshness budget")
                if not isinstance(self.state, str) or not _STATE.fullmatch(self.state):
                    raise HomeRigContractError("fresh observation requires a bounded source state")
            else:
                if expected_age <= self.max_freshness_seconds or self.state != "unknown":
                    raise HomeRigContractError("stale observations must normalize to unknown")
        object.__setattr__(self, "target_id", target_id)

    @property
    def source_id(self) -> str:
        return f"{self.source}:{self.target_id}"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source": self.source,
            "source_id": self.source_id,
            "capability_id": _CAPABILITY_ID[self.target_kind],
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "operation": self.operation,
            "state": self.state,
            "checked_at": _iso(self.checked_at),
            "observed_at": _iso(self.observed_at) if self.observed_at is not None else None,
            "freshness": self.freshness,
            "freshness_seconds": self.freshness_seconds,
            "max_freshness_seconds": self.max_freshness_seconds,
            "production_activation": False,
        }


def normalize_observation(
    *,
    target_kind: TargetKind,
    target_id: str,
    operation: str,
    source_state: str | None,
    observed_at: int | None,
    checked_at: int,
    max_freshness_seconds: int = 120,
) -> HomeRigObservation:
    """Fail closed: missing, unavailable or stale source evidence is unknown."""
    checked_at = _now(checked_at)
    operation = _operation(operation)
    if target_kind == "rig":
        source: Literal["riggate", "home_assistant"] = "riggate"
        target_id = _rig_id(target_id)
        if operation not in {"rig_health", "rig_power_readiness"}:
            raise HomeRigContractError("rig observation operation is invalid")
    elif target_kind == "entity":
        source = "home_assistant"
        target_id = _entity_id(target_id)
        if operation != "entity_state":
            raise HomeRigContractError("entity observation operation is invalid")
    else:
        raise HomeRigContractError("target_kind must be rig or entity")
    if (
        isinstance(max_freshness_seconds, bool)
        or not isinstance(max_freshness_seconds, int)
        or not 1 <= max_freshness_seconds <= _MAX_FRESHNESS_SECONDS
    ):
        raise HomeRigContractError("max freshness is invalid")
    if source_state is None or observed_at is None:
        return HomeRigObservation(
            source=source,
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,  # type: ignore[arg-type]
            state="unknown",
            checked_at=checked_at,
            observed_at=None,
            freshness="unavailable",
            freshness_seconds=None,
            max_freshness_seconds=max_freshness_seconds,
        )
    if not isinstance(source_state, str) or not _STATE.fullmatch(source_state):
        raise HomeRigContractError("source state is invalid")
    # Home Assistant and RigGate can return an explicit unavailable state with a
    # timestamp. It still means there is no usable source observation, so do not
    # let a recent timestamp make it look fresh/ready.
    if source_state.casefold() == "unavailable":
        return HomeRigObservation(
            source=source,
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,  # type: ignore[arg-type]
            state="unknown",
            checked_at=checked_at,
            observed_at=None,
            freshness="unavailable",
            freshness_seconds=None,
            max_freshness_seconds=max_freshness_seconds,
        )
    observed_at = _now(observed_at)
    if observed_at > checked_at:
        raise HomeRigContractError("source observation cannot be from the future")
    age = checked_at - observed_at
    freshness: Freshness = "fresh" if age <= max_freshness_seconds else "stale"
    state = source_state if freshness == "fresh" else "unknown"
    return HomeRigObservation(
        source=source,
        target_kind=target_kind,
        target_id=target_id,
        operation=operation,  # type: ignore[arg-type]
        state=state,
        checked_at=checked_at,
        observed_at=observed_at,
        freshness=freshness,
        freshness_seconds=age,
        max_freshness_seconds=max_freshness_seconds,
    )


@dataclass(frozen=True)
class HomeRigPreview:
    grant_id: str
    scope_sha256: str
    target_kind: TargetKind
    target_id: str
    action: str
    created_at: int
    schema: str = PREVIEW_SCHEMA
    would_execute: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != PREVIEW_SCHEMA:
            raise HomeRigContractError("unsupported preview schema")
        if self.would_execute is not False or self.production_activation is not False:
            raise HomeRigContractError("T-038 preview cannot execute or activate")
        if not _GRANT_ID.fullmatch(self.grant_id) or not _SHA256.fullmatch(self.scope_sha256):
            raise HomeRigContractError("preview authority identity is invalid")
        if self.target_kind == "rig":
            target = _rig_id(self.target_id)
            if self.action != "wake":
                raise HomeRigContractError("v1 rig preview supports wake only")
        elif self.target_kind == "entity":
            target = _entity_id(self.target_id)
            if self.action not in {"turn_on", "turn_off", "toggle"}:
                raise HomeRigContractError("v1 entity preview action is unsupported")
        else:
            raise HomeRigContractError("preview target_kind is invalid")
        _now(self.created_at)
        object.__setattr__(self, "target_id", target)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "action": self.action,
            "created_at": _iso(self.created_at),
            "would_execute": False,
            "production_activation": False,
        }


def build_control_preview(
    store: HomeRigGrantStore,
    grant_id: str,
    *,
    target_kind: TargetKind,
    target_id: str,
    action: str,
    now: int | None = None,
) -> HomeRigPreview:
    operation = "wake_preview" if target_kind == "rig" else "control_preview"
    grant = store.authorize(
        grant_id,
        target_kind=target_kind,
        target_id=target_id,
        operation=operation,
    )
    return HomeRigPreview(
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        target_kind=target_kind,
        target_id=target_id,
        action=action,
        created_at=_now(now),
    )


class HomeRigAuditLog:
    """Object-level audit without sensor values or control payloads."""

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS home_rig_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                connector TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                outcome TEXT NOT NULL,
                grant_id TEXT,
                scope_sha256 TEXT,
                freshness TEXT,
                detail TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record(
        self,
        *,
        target_kind: TargetKind,
        target_id: str,
        operation: str,
        outcome: AuditOutcome,
        detail: str,
        grant_id: str | None = None,
        scope_sha256: str | None = None,
        freshness: Freshness | None = None,
        now: int | None = None,
    ) -> None:
        operation = _operation(operation)
        if target_kind == "rig":
            target_id = _rig_id(target_id)
            connector = "riggate"
        elif target_kind == "entity":
            target_id = _entity_id(target_id)
            connector = "home_assistant"
        else:
            raise HomeRigContractError("audit target_kind is invalid")
        if outcome not in {"executed", "blocked", "error"}:
            raise HomeRigContractError("audit outcome is invalid")
        if not isinstance(detail, str) or not _DETAIL.fullmatch(detail):
            raise HomeRigContractError("audit detail must be a bounded categorical code")
        if grant_id is not None and not _GRANT_ID.fullmatch(grant_id):
            raise HomeRigContractError("audit grant_id is invalid")
        if scope_sha256 is not None and not _SHA256.fullmatch(scope_sha256):
            raise HomeRigContractError("audit scope digest is invalid")
        if freshness is not None and freshness not in {"fresh", "stale", "unavailable"}:
            raise HomeRigContractError("audit freshness is invalid")
        with self._lock:
            self._db.execute(
                "INSERT INTO home_rig_audit "
                "(ts,connector,target_kind,target_id,operation,outcome,grant_id,scope_sha256,freshness,detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    _now(now), connector, target_kind, target_id, operation,
                    outcome, grant_id, scope_sha256, freshness, detail,
                ),
            )
            self._db.commit()

    def recent(self, *, limit: int = 50) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise HomeRigContractError("audit limit must be between 1 and 500")
        with self._lock:
            rows = self._db.execute(
                "SELECT ts,connector,target_kind,target_id,operation,outcome,grant_id,"
                "scope_sha256,freshness,detail FROM home_rig_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**dict(row), "ts": _iso(row["ts"])} for row in rows]


def build_home_rig_sharing_request(
    scope: HomeRigScope,
    *,
    target_kind: TargetKind,
    data_category: str,
    purpose_code: str,
    purpose: str,
    summary: str,
    content_sha256: str,
    max_bytes: int,
) -> DataSharingRequest:
    """Bind any data sent into the connector to T-032's exact policy request."""
    if not isinstance(scope, HomeRigScope):
        raise HomeRigContractError("data sharing requires HomeRigScope")
    if target_kind == "rig":
        if not scope.rig_ids:
            raise HomeRigContractError("RigGate sharing requires rig scope")
        provider = "riggate"
    elif target_kind == "entity":
        if not scope.entity_ids:
            raise HomeRigContractError("Home Assistant sharing requires entity scope")
        provider = "home_assistant"
    else:
        raise HomeRigContractError("sharing target_kind is invalid")
    return DataSharingRequest(
        surface="connector",
        destination_type="connector",
        provider=provider,
        destination=f"{provider}/{scope.digest}",
        data_category=data_category,  # type: ignore[arg-type]
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
        content_sha256=content_sha256,
        max_bytes=max_bytes,
    )
