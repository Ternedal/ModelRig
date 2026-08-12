"""T-037 dormant authority for Google/Notion read-first connectors.

This module deliberately contains no network client, credential provider, route,
ToolGate registration or product activation.  It defines the reusable authority
that later connector implementations must consume rather than inventing their
own allowlists:

* four separate connector/capability identities;
* exact account/workspace/object/read-operation scopes;
* durable grants whose revocation is re-read before every authorization;
* readiness that cannot be green without both active scope and credential
  readiness, while never storing credential material;
* privacy-minimized source receipts and connector audit;
* a T-032 DataSharingRequest adapter for cross-connector processing.

`production_activation` is structurally false throughout.
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

from .data_sharing import DataSharingRequest

SCOPE_SCHEMA = "kaliv-read-connector-scope/v1"
GRANT_SCHEMA = "kaliv-read-connector-grant/v1"
SOURCE_SCHEMA = "kaliv-read-connector-source/v1"
READINESS_SCHEMA = "kaliv-read-connector-readiness/v1"
PRODUCTION_ACTIVATION = False

Connector = Literal["google_calendar", "google_drive", "gmail", "notion"]
CredentialState = Literal[
    "ready",
    "missing_credentials",
    "expired_credentials",
    "invalid_credentials",
    "unavailable",
]
ReadinessState = Literal[
    "ready",
    "missing_scope",
    "revoked",
    "missing_credentials",
    "expired_credentials",
    "invalid_credentials",
    "unavailable",
]
AuditOutcome = Literal["executed", "blocked", "error"]

_CONNECTORS: tuple[Connector, ...] = (
    "google_calendar",
    "google_drive",
    "gmail",
    "notion",
)
_CONNECTOR_SET = frozenset(_CONNECTORS)
_PROVIDER = {
    "google_calendar": "google",
    "google_drive": "google",
    "gmail": "google",
    "notion": "notion",
}
_CAPABILITY_ID = {
    "google_calendar": "tool:google_calendar_read",
    "google_drive": "tool:google_drive_read",
    "gmail": "tool:gmail_read",
    "notion": "tool:notion_read",
}
_ALLOWED_OPERATIONS: dict[Connector, tuple[str, ...]] = {
    "google_calendar": ("calendar_list", "event_get", "event_search"),
    "google_drive": ("file_search", "file_metadata", "document_read"),
    "gmail": ("message_search", "message_get", "thread_get"),
    "notion": ("search", "page_get", "database_query"),
}

# Stable provider identities only.  E-mail addresses, URLs, query strings and
# arbitrary display names are deliberately not authority identifiers.
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+-]{0,255}$")
_GRANT_ID = re.compile(r"^rcg_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+-]{0,255}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_DETAIL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")


class ReadConnectorContractError(ValueError):
    """A T-037 authority value is malformed or contradictory."""


class ReadConnectorDenied(PermissionError):
    """The requested read is not covered by one active exact grant."""


def connectors() -> tuple[Connector, ...]:
    return _CONNECTORS


def capability_id(connector: Connector) -> str:
    connector = normalize_connector(connector)
    return _CAPABILITY_ID[connector]


def allowed_operations(connector: Connector) -> tuple[str, ...]:
    connector = normalize_connector(connector)
    return _ALLOWED_OPERATIONS[connector]


def normalize_connector(value: str) -> Connector:
    if not isinstance(value, str) or value not in _CONNECTOR_SET:
        raise ReadConnectorContractError("unsupported read connector")
    return value  # type: ignore[return-value]


def _ref(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorContractError(f"{name} must be a string")
    value = value.strip()
    if not _REF.fullmatch(value):
        raise ReadConnectorContractError(
            f"{name} must be an exact stable provider identifier"
        )
    return value


def _operation(connector: Connector, value: str) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_OPERATIONS[connector]:
        raise ReadConnectorContractError(
            f"unsupported {connector} read operation"
        )
    return value


def _actor(value: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorContractError("actor must be a string")
    value = " ".join(value.split())
    if not value or len(value) > 100:
        raise ReadConnectorContractError("actor must contain 1..100 characters")
    return value


def _now(value: int | None) -> int:
    value = int(time.time()) if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadConnectorContractError("now must be a non-negative integer")
    return value


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class ReadConnectorScope:
    connector: Connector
    account_ref: str
    object_scopes: tuple[str, ...]
    operations: tuple[str, ...]
    workspace_ref: str | None = None
    schema: str = SCOPE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != SCOPE_SCHEMA:
            raise ReadConnectorContractError("unsupported connector scope schema")
        if self.production_activation is not False:
            raise ReadConnectorContractError("production activation must remain false")
        connector = normalize_connector(self.connector)
        account_ref = _ref(self.account_ref, "account_ref")
        workspace_ref = (
            _ref(self.workspace_ref, "workspace_ref")
            if self.workspace_ref is not None
            else None
        )
        if connector == "notion" and workspace_ref is None:
            raise ReadConnectorContractError("notion scope requires workspace_ref")
        if not isinstance(self.object_scopes, tuple) or not self.object_scopes:
            raise ReadConnectorContractError("at least one exact object scope is required")
        object_scopes = tuple(_ref(item, "object_scope") for item in self.object_scopes)
        if len(object_scopes) != len(set(object_scopes)):
            raise ReadConnectorContractError("object scope contains duplicates")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise ReadConnectorContractError("at least one read operation is required")
        operations = tuple(_operation(connector, item) for item in self.operations)
        if len(operations) != len(set(operations)):
            raise ReadConnectorContractError("operation scope contains duplicates")

        object.__setattr__(self, "connector", connector)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "workspace_ref", workspace_ref)
        object.__setattr__(self, "object_scopes", tuple(sorted(object_scopes)))
        object.__setattr__(
            self,
            "operations",
            tuple(item for item in _ALLOWED_OPERATIONS[connector] if item in operations),
        )

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "object_scopes": list(self.object_scopes),
            "operations": list(self.operations),
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @property
    def provider(self) -> str:
        return _PROVIDER[self.connector]

    @property
    def data_sharing_destination(self) -> str:
        # T-032 needs a stable destination identity, not raw account/workspace
        # material.  Binding the destination to the canonical exact scope also
        # means any authority widening/narrowing produces a different request.
        return f"{self.connector}/{self.digest}"

    def allows(self, *, object_scope: str, operation: str) -> bool:
        scope = _ref(object_scope, "object_scope")
        op = _operation(self.connector, operation)
        return scope in self.object_scopes and op in self.operations


@dataclass(frozen=True)
class ReadConnectorGrant:
    grant_id: str
    scope: ReadConnectorScope
    created_at: int
    created_by: str
    revoked_at: int | None = None
    revoked_by: str | None = None
    schema: str = GRANT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GRANT_SCHEMA:
            raise ReadConnectorContractError("unsupported connector grant schema")
        if not isinstance(self.grant_id, str) or not _GRANT_ID.fullmatch(self.grant_id):
            raise ReadConnectorContractError("grant_id has invalid format")
        if not isinstance(self.scope, ReadConnectorScope):
            raise ReadConnectorContractError("grant scope is invalid")
        created_at = _now(self.created_at)
        created_by = _actor(self.created_by)
        if self.revoked_at is None:
            if self.revoked_by is not None:
                raise ReadConnectorContractError("active grant cannot have revoked_by")
        else:
            revoked_at = _now(self.revoked_at)
            if revoked_at < created_at:
                raise ReadConnectorContractError("revocation predates grant")
            if self.revoked_by is None:
                raise ReadConnectorContractError("revoked grant requires revoked_by")
            _actor(self.revoked_by)
        object.__setattr__(self, "created_by", created_by)

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope": self.scope.to_dict(),
            "scope_sha256": self.scope.digest,
            "created_at": _iso(self.created_at),
            "created_by": self.created_by,
            "status": "active" if self.active else "revoked",
            "revoked_at": _iso(self.revoked_at) if self.revoked_at is not None else None,
            "revoked_by": self.revoked_by,
            "production_activation": False,
        }


class ReadConnectorGrantStore:
    """Durable exact read authority; every authorization re-reads SQLite."""

    def __init__(
        self,
        path: str = ":memory:",
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS read_connector_grants (
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

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create_grant(
        self,
        scope: ReadConnectorScope,
        *,
        actor: str,
        now: int | None = None,
    ) -> ReadConnectorGrant:
        if not isinstance(scope, ReadConnectorScope):
            raise ReadConnectorContractError("scope must be ReadConnectorScope")
        now = _now(now)
        actor = _actor(actor)
        grant = ReadConnectorGrant(
            grant_id=f"rcg_{self._uuid_factory().hex}",
            scope=scope,
            created_at=now,
            created_by=actor,
        )
        with self._lock:
            self._db.execute(
                "INSERT INTO read_connector_grants VALUES (?,?,?,?,?,?,?)",
                (
                    grant.grant_id,
                    json.dumps(scope.to_dict(), sort_keys=True, separators=(",", ":")),
                    scope.digest,
                    now,
                    actor,
                    None,
                    None,
                ),
            )
        return grant

    def _decode(self, row: sqlite3.Row) -> ReadConnectorGrant:
        raw = json.loads(row["scope_json"])
        if raw.get("schema") != SCOPE_SCHEMA or raw.get("production_activation") is not False:
            raise ReadConnectorContractError("stored connector scope is not canonical v1")
        scope = ReadConnectorScope(
            connector=raw["connector"],
            account_ref=raw["account_ref"],
            workspace_ref=raw.get("workspace_ref"),
            object_scopes=tuple(raw["object_scopes"]),
            operations=tuple(raw["operations"]),
        )
        if scope.digest != row["scope_sha256"]:
            raise ReadConnectorContractError("stored connector scope digest mismatch")
        return ReadConnectorGrant(
            grant_id=row["grant_id"],
            scope=scope,
            created_at=row["created_at"],
            created_by=row["created_by"],
            revoked_at=row["revoked_at"],
            revoked_by=row["revoked_by"],
        )

    def get_grant(self, grant_id: str) -> ReadConnectorGrant | None:
        if not isinstance(grant_id, str) or not _GRANT_ID.fullmatch(grant_id):
            raise ReadConnectorContractError("grant_id has invalid format")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM read_connector_grants WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def list_grants(
        self,
        *,
        connector: Connector | None = None,
        include_revoked: bool = False,
    ) -> tuple[ReadConnectorGrant, ...]:
        normalized = normalize_connector(connector) if connector is not None else None
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM read_connector_grants ORDER BY created_at, grant_id"
            ).fetchall()
        grants = tuple(self._decode(row) for row in rows)
        return tuple(
            grant
            for grant in grants
            if (include_revoked or grant.active)
            and (normalized is None or grant.scope.connector == normalized)
        )

    def authorize(
        self,
        grant_id: str,
        *,
        connector: Connector,
        account_ref: str,
        workspace_ref: str | None,
        object_scope: str,
        operation: str,
    ) -> ReadConnectorGrant:
        grant = self.get_grant(grant_id)
        if grant is None or not grant.active:
            raise ReadConnectorDenied("connector grant is missing or revoked")
        connector = normalize_connector(connector)
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = (
            _ref(workspace_ref, "workspace_ref") if workspace_ref is not None else None
        )
        if (
            grant.scope.connector != connector
            or grant.scope.account_ref != account_ref
            or grant.scope.workspace_ref != workspace_ref
            or not grant.scope.allows(object_scope=object_scope, operation=operation)
        ):
            raise ReadConnectorDenied("connector read is outside exact active scope")
        return grant

    def revoke(
        self,
        grant_id: str,
        *,
        expected_scope_sha256: str,
        actor: str,
        now: int | None = None,
    ) -> ReadConnectorGrant:
        if not isinstance(expected_scope_sha256, str) or not _SHA256.fullmatch(
            expected_scope_sha256
        ):
            raise ReadConnectorContractError(
                "expected_scope_sha256 must be lowercase SHA-256"
            )
        now = _now(now)
        actor = _actor(actor)
        with self._lock:
            current = self.get_grant(grant_id)
            if current is None:
                raise ReadConnectorDenied("unknown connector grant")
            if current.scope.digest != expected_scope_sha256:
                raise ReadConnectorDenied("connector scope changed before revoke")
            if current.active:
                self._db.execute(
                    "UPDATE read_connector_grants SET revoked_at=?, revoked_by=? "
                    "WHERE grant_id=? AND revoked_at IS NULL",
                    (now, actor, grant_id),
                )
            updated = self.get_grant(grant_id)
        assert updated is not None
        return updated


@dataclass(frozen=True)
class ReadConnectorReadiness:
    connector: Connector
    account_ref: str | None
    workspace_ref: str | None
    grant_id: str | None
    scope_sha256: str | None
    state: ReadinessState
    checked_at: int
    schema: str = READINESS_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != READINESS_SCHEMA:
            raise ReadConnectorContractError("unsupported readiness schema")
        if self.production_activation is not False:
            raise ReadConnectorContractError("production activation must remain false")
        normalize_connector(self.connector)
        _now(self.checked_at)
        if self.account_ref is not None:
            _ref(self.account_ref, "account_ref")
        if self.workspace_ref is not None:
            _ref(self.workspace_ref, "workspace_ref")
        if self.grant_id is not None and not _GRANT_ID.fullmatch(self.grant_id):
            raise ReadConnectorContractError("readiness grant_id has invalid format")
        if self.scope_sha256 is not None and not _SHA256.fullmatch(self.scope_sha256):
            raise ReadConnectorContractError("readiness scope digest is invalid")
        if self.state == "ready" and (
            self.grant_id is None or self.scope_sha256 is None or self.account_ref is None
        ):
            raise ReadConnectorContractError("ready state requires exact grant scope evidence")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "state": self.state,
            "checked_at": _iso(self.checked_at),
            "production_activation": False,
        }


def readiness_for(
    store: ReadConnectorGrantStore,
    *,
    connector: Connector,
    grant_id: str,
    credential_state: CredentialState,
    checked_at: int | None = None,
) -> ReadConnectorReadiness:
    connector = normalize_connector(connector)
    checked_at = _now(checked_at)
    if credential_state not in {
        "ready",
        "missing_credentials",
        "expired_credentials",
        "invalid_credentials",
        "unavailable",
    }:
        raise ReadConnectorContractError("unsupported credential readiness state")
    grant = store.get_grant(grant_id)
    if grant is None or grant.scope.connector != connector:
        return ReadConnectorReadiness(
            connector=connector,
            account_ref=None,
            workspace_ref=None,
            grant_id=None,
            scope_sha256=None,
            state="missing_scope",
            checked_at=checked_at,
        )
    if not grant.active:
        state: ReadinessState = "revoked"
    else:
        state = credential_state
    return ReadConnectorReadiness(
        connector=connector,
        account_ref=grant.scope.account_ref,
        workspace_ref=grant.scope.workspace_ref,
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        state=state,
        checked_at=checked_at,
    )


@dataclass(frozen=True)
class ReadConnectorSourceReceipt:
    connector: Connector
    grant_id: str
    scope_sha256: str
    account_ref: str
    workspace_ref: str | None
    object_scope: str
    operation: str
    source_id: str
    object_id: str
    revision: str
    retrieved_at: int
    schema: str = SOURCE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != SOURCE_SCHEMA:
            raise ReadConnectorContractError("unsupported source receipt schema")
        if self.production_activation is not False:
            raise ReadConnectorContractError("production activation must remain false")
        connector = normalize_connector(self.connector)
        if not _GRANT_ID.fullmatch(self.grant_id):
            raise ReadConnectorContractError("source grant_id has invalid format")
        if not _SHA256.fullmatch(self.scope_sha256):
            raise ReadConnectorContractError("source scope_sha256 is invalid")
        account_ref = _ref(self.account_ref, "account_ref")
        workspace_ref = (
            _ref(self.workspace_ref, "workspace_ref")
            if self.workspace_ref is not None
            else None
        )
        object_scope = _ref(self.object_scope, "object_scope")
        operation = _operation(connector, self.operation)
        if not isinstance(self.source_id, str) or not _SOURCE_ID.fullmatch(self.source_id):
            raise ReadConnectorContractError("source_id has invalid format")
        if not isinstance(self.object_id, str) or not _SOURCE_ID.fullmatch(self.object_id):
            raise ReadConnectorContractError("object_id has invalid format")
        if not isinstance(self.revision, str) or not _REVISION.fullmatch(self.revision):
            raise ReadConnectorContractError("revision has invalid format")
        _now(self.retrieved_at)
        object.__setattr__(self, "connector", connector)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "workspace_ref", workspace_ref)
        object.__setattr__(self, "object_scope", object_scope)
        object.__setattr__(self, "operation", operation)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "object_scope": self.object_scope,
            "operation": self.operation,
            "source_id": self.source_id,
            "object_id": self.object_id,
            "revision": self.revision,
            "retrieved_at": _iso(self.retrieved_at),
            "production_activation": False,
        }


class ReadConnectorAuditLog:
    """Connector/account/scope audit with no document body or credential field."""

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS read_connector_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                connector TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                workspace_ref TEXT,
                object_scope TEXT NOT NULL,
                operation TEXT NOT NULL,
                outcome TEXT NOT NULL,
                grant_id TEXT,
                scope_sha256 TEXT,
                source_id TEXT,
                object_id TEXT,
                revision TEXT,
                duration_ms INTEGER NOT NULL,
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
        connector: Connector,
        account_ref: str,
        workspace_ref: str | None,
        object_scope: str,
        operation: str,
        outcome: AuditOutcome,
        duration_ms: int,
        detail: str,
        grant_id: str | None = None,
        scope_sha256: str | None = None,
        source_id: str | None = None,
        object_id: str | None = None,
        revision: str | None = None,
    ) -> None:
        connector = normalize_connector(connector)
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = (
            _ref(workspace_ref, "workspace_ref") if workspace_ref is not None else None
        )
        object_scope = _ref(object_scope, "object_scope")
        operation = _operation(connector, operation)
        if outcome not in {"executed", "blocked", "error"}:
            raise ReadConnectorContractError("unsupported connector audit outcome")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
            raise ReadConnectorContractError("duration_ms must be a non-negative integer")
        if not isinstance(detail, str) or not _DETAIL.fullmatch(detail):
            raise ReadConnectorContractError("detail must be one bounded categorical code")
        if grant_id is not None and not _GRANT_ID.fullmatch(grant_id):
            raise ReadConnectorContractError("audit grant_id has invalid format")
        if scope_sha256 is not None and not _SHA256.fullmatch(scope_sha256):
            raise ReadConnectorContractError("audit scope_sha256 is invalid")
        for name, value in (("source_id", source_id), ("object_id", object_id)):
            if value is not None and not _SOURCE_ID.fullmatch(value):
                raise ReadConnectorContractError(f"audit {name} has invalid format")
        if revision is not None and not _REVISION.fullmatch(revision):
            raise ReadConnectorContractError("audit revision has invalid format")
        with self._lock:
            self._db.execute(
                """
                INSERT INTO read_connector_audit (
                    ts, connector, account_ref, workspace_ref, object_scope,
                    operation, outcome, grant_id, scope_sha256, source_id,
                    object_id, revision, duration_ms, detail
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _iso(_now(None)),
                    connector,
                    account_ref,
                    workspace_ref,
                    object_scope,
                    operation,
                    outcome,
                    grant_id,
                    scope_sha256,
                    source_id,
                    object_id,
                    revision,
                    duration_ms,
                    detail,
                ),
            )
            self._db.commit()

    def recent(
        self,
        *,
        limit: int = 50,
        connector: Connector | None = None,
        account_ref: str | None = None,
        object_scope: str | None = None,
        operation: str | None = None,
        outcome: AuditOutcome | None = None,
    ) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReadConnectorContractError("limit must be between 1 and 500")
        clauses: list[str] = []
        values: list[object] = []
        if connector is not None:
            connector = normalize_connector(connector)
            clauses.append("connector=?")
            values.append(connector)
        if account_ref is not None:
            account_ref = _ref(account_ref, "account_ref")
            clauses.append("account_ref=?")
            values.append(account_ref)
        if object_scope is not None:
            object_scope = _ref(object_scope, "object_scope")
            clauses.append("object_scope=?")
            values.append(object_scope)
        if operation is not None:
            if connector is None:
                raise ReadConnectorContractError(
                    "operation audit filter requires connector"
                )
            operation = _operation(connector, operation)
            clauses.append("operation=?")
            values.append(operation)
        if outcome is not None:
            if outcome not in {"executed", "blocked", "error"}:
                raise ReadConnectorContractError("unsupported connector audit outcome")
            clauses.append("outcome=?")
            values.append(outcome)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, connector, account_ref, workspace_ref, object_scope,"
                " operation, outcome, grant_id, scope_sha256, source_id, object_id,"
                " revision, duration_ms, detail FROM read_connector_audit"
                f"{where} ORDER BY id DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]


def build_cross_connector_sharing_request(
    *,
    source_connector: Connector,
    destination_scope: ReadConnectorScope,
    data_category: str,
    purpose_code: str,
    purpose: str,
    summary: str,
    content_sha256: str,
    max_bytes: int,
) -> DataSharingRequest:
    """Bind cross-connector processing to T-032's exact request authority.

    The returned request is not an authorization.  Callers must still pass it
    through DataSharingLedger/DEFAULT_POLICY and consume the resulting receipt.
    """
    source_connector = normalize_connector(source_connector)
    if not isinstance(destination_scope, ReadConnectorScope):
        raise ReadConnectorContractError("destination_scope must be exact connector scope")
    if source_connector == destination_scope.connector:
        raise ReadConnectorContractError("cross-connector sharing requires two connectors")
    return DataSharingRequest(
        surface="connector",
        destination_type="connector",
        provider=destination_scope.provider,
        destination=destination_scope.data_sharing_destination,
        data_category=data_category,  # type: ignore[arg-type]
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
        content_sha256=content_sha256,
        max_bytes=max_bytes,
    )
