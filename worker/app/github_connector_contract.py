"""T-036 dormant contract for a scoped, read-only GitHub connector pilot.

This module deliberately performs no network I/O, reads no credentials and
registers no ToolGate tool.  It lands the security authority first:

* one grant names an explicit account, exact repositories and read operations;
* grants are durable and revocable;
* every authorization re-reads durable state, so revocation stops later calls;
* source receipts bind repository id, object id, revision and retrieval time;
* no token, content, issue body, PR body or other user data enters the grant DB.

The later transport/tool slice must consume this authority rather than creating
a parallel allowlist.  `production_activation` remains false.
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

from . import paths as _paths

SCOPE_SCHEMA = "kaliv-github-connector-scope/v1"
GRANT_SCHEMA = "kaliv-github-connector-grant/v1"
SOURCE_SCHEMA = "kaliv-github-source-receipt/v1"
PRODUCTION_ACTIVATION = False

GitHubReadOperation = Literal["repository", "issue", "pull_request", "workflow_run"]
GitHubObjectType = Literal["repository", "issue", "pull_request", "workflow_run"]

_ALLOWED_OPERATIONS = ("repository", "issue", "pull_request", "workflow_run")
_ALLOWED_OPERATION_SET = frozenset(_ALLOWED_OPERATIONS)
_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_ACCOUNT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_GRANT_ID = re.compile(r"^ghg_[0-9a-f]{32}$")
_REVISION = re.compile(r"^[A-Za-z0-9._:/+-]{1,160}$")
_OBJECT_ID = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_DEFAULT_DB = _paths.resolve(
    "./kaliv-github-connector.db", env="KALIV_GITHUB_CONNECTOR_DB"
)


class GitHubConnectorContractError(ValueError):
    """A connector scope/source value is malformed or contradictory."""


class GitHubConnectorDenied(PermissionError):
    """The requested GitHub read is outside active durable authority."""


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _now(value: int | None) -> int:
    value = int(time.time()) if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GitHubConnectorContractError("now must be a non-negative integer")
    return value


def _actor(value: str) -> str:
    if not isinstance(value, str):
        raise GitHubConnectorContractError("actor must be a string")
    value = " ".join(value.split())
    if not value or len(value) > 100:
        raise GitHubConnectorContractError("actor must contain 1..100 characters")
    return value


def normalize_account(value: str) -> str:
    if not isinstance(value, str):
        raise GitHubConnectorContractError("account must be a string")
    value = value.strip()
    if not _ACCOUNT.fullmatch(value):
        raise GitHubConnectorContractError("account must be an exact GitHub login")
    return value.lower()


def normalize_repository(value: str) -> str:
    if not isinstance(value, str):
        raise GitHubConnectorContractError("repository must be a string")
    value = value.strip()
    if not _REPOSITORY.fullmatch(value):
        raise GitHubConnectorContractError("repository must be exact owner/name")
    owner, name = value.split("/", 1)
    if name in {".", ".."} or name.lower().endswith(".git"):
        raise GitHubConnectorContractError("repository must be canonical owner/name")
    return f"{owner.lower()}/{name.lower()}"


def normalize_operation(value: str) -> GitHubReadOperation:
    if value not in _ALLOWED_OPERATION_SET:
        raise GitHubConnectorContractError("unsupported GitHub read operation")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class GitHubConnectorScope:
    """Exact durable authority: account + repositories + read operation set."""

    account: str
    repositories: tuple[str, ...]
    operations: tuple[GitHubReadOperation, ...] = _ALLOWED_OPERATIONS
    schema: str = SCOPE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != SCOPE_SCHEMA:
            raise GitHubConnectorContractError("unsupported GitHub scope schema")
        if self.production_activation is not False:
            raise GitHubConnectorContractError("production activation must remain false")
        account = normalize_account(self.account)
        if not isinstance(self.repositories, tuple) or not self.repositories:
            raise GitHubConnectorContractError("at least one exact repository is required")
        repositories = tuple(normalize_repository(item) for item in self.repositories)
        if len(repositories) != len(set(repositories)):
            raise GitHubConnectorContractError("repository scope contains duplicates")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise GitHubConnectorContractError("at least one read operation is required")
        operations = tuple(normalize_operation(item) for item in self.operations)
        if len(operations) != len(set(operations)):
            raise GitHubConnectorContractError("operation scope contains duplicates")
        # Canonical ordering makes the digest independent of UI ordering.
        object.__setattr__(self, "account", account)
        object.__setattr__(self, "repositories", tuple(sorted(repositories)))
        object.__setattr__(
            self,
            "operations",
            tuple(item for item in _ALLOWED_OPERATIONS if item in operations),
        )

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "account": self.account,
            "repositories": list(self.repositories),
            "operations": list(self.operations),
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def allows(self, repository: str, operation: str) -> bool:
        repo = normalize_repository(repository)
        op = normalize_operation(operation)
        return repo in self.repositories and op in self.operations


@dataclass(frozen=True)
class GitHubConnectorGrant:
    grant_id: str
    scope: GitHubConnectorScope
    created_at: int
    created_by: str
    revoked_at: int | None = None
    revoked_by: str | None = None
    schema: str = GRANT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GRANT_SCHEMA:
            raise GitHubConnectorContractError("unsupported GitHub grant schema")
        if not isinstance(self.grant_id, str) or not _GRANT_ID.fullmatch(self.grant_id):
            raise GitHubConnectorContractError("grant_id has invalid format")
        if not isinstance(self.scope, GitHubConnectorScope):
            raise GitHubConnectorContractError("grant scope is invalid")
        _now(self.created_at)
        _actor(self.created_by)
        if self.revoked_at is None:
            if self.revoked_by is not None:
                raise GitHubConnectorContractError("active grant cannot have revoked_by")
        else:
            _now(self.revoked_at)
            if self.revoked_at < self.created_at:
                raise GitHubConnectorContractError("revocation predates grant")
            if self.revoked_by is None:
                raise GitHubConnectorContractError("revoked grant requires revoked_by")
            _actor(self.revoked_by)

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


@dataclass(frozen=True)
class GitHubSourceReceipt:
    """Privacy-minimized provenance for one successful GitHub read."""

    grant_id: str
    scope_sha256: str
    repository: str
    repository_id: int
    object_type: GitHubObjectType
    object_id: str
    revision: str
    retrieved_at: int
    schema: str = SOURCE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != SOURCE_SCHEMA:
            raise GitHubConnectorContractError("unsupported GitHub source schema")
        if self.production_activation is not False:
            raise GitHubConnectorContractError("production activation must remain false")
        if not _GRANT_ID.fullmatch(self.grant_id):
            raise GitHubConnectorContractError("source grant_id has invalid format")
        if not isinstance(self.scope_sha256, str) or not _SHA256.fullmatch(self.scope_sha256):
            raise GitHubConnectorContractError("scope_sha256 must be lowercase SHA-256")
        object.__setattr__(self, "repository", normalize_repository(self.repository))
        if isinstance(self.repository_id, bool) or not isinstance(self.repository_id, int):
            raise GitHubConnectorContractError("repository_id must be an integer")
        if self.repository_id <= 0:
            raise GitHubConnectorContractError("repository_id must be positive")
        if self.object_type not in _ALLOWED_OPERATION_SET:
            raise GitHubConnectorContractError("object_type is unsupported")
        if not isinstance(self.object_id, str) or not _OBJECT_ID.fullmatch(self.object_id):
            raise GitHubConnectorContractError("object_id has invalid format")
        if not isinstance(self.revision, str) or not _REVISION.fullmatch(self.revision):
            raise GitHubConnectorContractError("revision has invalid format")
        _now(self.retrieved_at)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "connector": "github",
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "revision": self.revision,
            "retrieved_at": _iso(self.retrieved_at),
            "production_activation": False,
        }


class GitHubConnectorGrantStore:
    """Durable grant authority. Every authorization consults current DB state."""

    def __init__(
        self,
        path: str = _DEFAULT_DB,
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.path = path
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS github_connector_grants (
                grant_id TEXT PRIMARY KEY,
                account TEXT NOT NULL,
                repositories_json TEXT NOT NULL,
                operations_json TEXT NOT NULL,
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

    def _from_row(self, row: sqlite3.Row) -> GitHubConnectorGrant:
        scope = GitHubConnectorScope(
            account=row["account"],
            repositories=tuple(json.loads(row["repositories_json"])),
            operations=tuple(json.loads(row["operations_json"])),
        )
        if scope.digest != row["scope_sha256"]:
            raise GitHubConnectorDenied("stored GitHub scope digest is corrupt")
        return GitHubConnectorGrant(
            grant_id=row["grant_id"],
            scope=scope,
            created_at=row["created_at"],
            created_by=row["created_by"],
            revoked_at=row["revoked_at"],
            revoked_by=row["revoked_by"],
        )

    def create(
        self,
        scope: GitHubConnectorScope,
        *,
        actor: str,
        now: int | None = None,
    ) -> GitHubConnectorGrant:
        if not isinstance(scope, GitHubConnectorScope):
            raise GitHubConnectorContractError("scope must be GitHubConnectorScope")
        timestamp = _now(now)
        actor = _actor(actor)
        grant_id = f"ghg_{self._uuid_factory().hex}"
        with self._lock:
            self._db.execute(
                "INSERT INTO github_connector_grants VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    grant_id,
                    scope.account,
                    json.dumps(list(scope.repositories), separators=(",", ":")),
                    json.dumps(list(scope.operations), separators=(",", ":")),
                    scope.digest,
                    timestamp,
                    actor,
                    None,
                    None,
                ),
            )
        return GitHubConnectorGrant(grant_id, scope, timestamp, actor)

    def get(self, grant_id: str) -> GitHubConnectorGrant | None:
        if not isinstance(grant_id, str) or not _GRANT_ID.fullmatch(grant_id):
            raise GitHubConnectorContractError("grant_id has invalid format")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM github_connector_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_grants(self, *, include_revoked: bool = False) -> tuple[GitHubConnectorGrant, ...]:
        query = "SELECT * FROM github_connector_grants"
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        query += " ORDER BY created_at DESC, grant_id DESC"
        with self._lock:
            rows = self._db.execute(query).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def revoke(
        self,
        grant_id: str,
        *,
        actor: str,
        now: int | None = None,
    ) -> GitHubConnectorGrant:
        timestamp = _now(now)
        actor = _actor(actor)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM github_connector_grants WHERE grant_id=?", (grant_id,)
                ).fetchone()
                if row is None:
                    raise GitHubConnectorDenied("unknown GitHub connector grant")
                if row["revoked_at"] is None:
                    self._db.execute(
                        "UPDATE github_connector_grants "
                        "SET revoked_at=?, revoked_by=? WHERE grant_id=? AND revoked_at IS NULL",
                        (timestamp, actor, grant_id),
                    )
                row = self._db.execute(
                    "SELECT * FROM github_connector_grants WHERE grant_id=?", (grant_id,)
                ).fetchone()
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        assert row is not None
        return self._from_row(row)

    def authorize(
        self,
        grant_id: str,
        *,
        repository: str,
        operation: str,
    ) -> GitHubConnectorGrant:
        """Return current grant only if this exact read remains authorized."""
        grant = self.get(grant_id)
        if grant is None:
            raise GitHubConnectorDenied("unknown GitHub connector grant")
        if not grant.active:
            raise GitHubConnectorDenied("GitHub connector grant is revoked")
        if not grant.scope.allows(repository, operation):
            raise GitHubConnectorDenied("GitHub read is outside the granted scope")
        return grant
