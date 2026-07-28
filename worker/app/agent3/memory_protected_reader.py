from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .memory import MemoryNotFound, MemoryRecord, MemoryStoreError
from .memory_protection import (
    ENVELOPE_SCHEMA,
    MemoryProtectionCodec,
    MemoryProtectionError,
    MemoryProtectionScope,
    PROTECTED_SENSITIVITIES,
)
from .memory_protection_migration import (
    MIGRATION_ID,
    MIGRATION_SCHEMA,
    PROTECTION_REVISION,
)


class ProtectedMemoryReadError(MemoryStoreError):
    """A migrated memory store cannot be read without weakening protection."""


class MemoryReadAccess(str, Enum):
    METADATA_ONLY = "metadata_only"
    LOCAL_CONTEXT = "local_context"
    LOCAL_MANAGEMENT = "local_management"


@dataclass(frozen=True)
class ProtectedMemoryReaderStatus:
    schema: str
    migration_id: str
    provider: str
    key_scope: str
    migration_state: str
    protected_rows: int
    redacted_rows: int
    public_operational_rows: int
    query_only: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "migration_id": self.migration_id,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "migration_state": self.migration_state,
            "protected_rows": self.protected_rows,
            "redacted_rows": self.redacted_rows,
            "public_operational_rows": self.public_operational_rows,
            "query_only": self.query_only,
            "production_activation": False,
        }


_REQUIRED_COLUMNS = {
    "id",
    "subject",
    "predicate",
    "value",
    "kind",
    "sensitivity",
    "source_type",
    "source_ref",
    "confidence",
    "review_status",
    "lifecycle_status",
    "supersedes_id",
    "created_at",
    "updated_at",
    "expires_at",
    "deleted_at",
    "schema_version",
    "value_protected",
    "source_ref_protected",
    "protection_schema",
    "protection_provider",
    "protection_key_scope",
    "protection_state",
    "protection_fields",
    "protection_revision",
    "protection_updated_at",
}
_LIFECYCLE_STATES = frozenset({"active", "superseded", "deleted"})
_REVIEW_STATES = frozenset({"pending", "confirmed", "rejected"})


class ProtectedMemoryReader:
    """Explicit, query-only boundary for a completed protected migration.

    The class is intentionally not wired into startup or HTTP routes. It exposes
    no writes and never searches plaintext values, envelope JSON or ciphertext.
    """

    def __init__(
        self,
        path: str | Path,
        codec: MemoryProtectionCodec,
        *,
        busy_timeout_ms: int = 5_000,
    ):
        self.path = Path(path)
        self.codec = codec
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))
        self._closed = False
        self._conn: sqlite3.Connection | None = None
        self._validate_path()
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        try:
            self._conn = sqlite3.connect(
                uri,
                uri=True,
                check_same_thread=False,
                timeout=self.busy_timeout_ms / 1000.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA query_only=ON")
            self._status = self._validate_store()
        except (sqlite3.Error, MemoryProtectionError, ProtectedMemoryReadError) as exc:
            self._close_connection()
            if isinstance(exc, ProtectedMemoryReadError):
                raise
            raise ProtectedMemoryReadError(
                f"protected memory reader failed closed: {type(exc).__name__}"
            ) from exc

    @property
    def status(self) -> ProtectedMemoryReaderStatus:
        self._require_open()
        return self._status

    def close(self) -> None:
        self._close_connection()
        self._closed = True

    def _close_connection(self) -> None:
        connection = self._conn
        self._conn = None
        if connection is not None:
            connection.close()

    def __enter__(self) -> "ProtectedMemoryReader":
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def get(
        self,
        memory_id: str,
        *,
        access: MemoryReadAccess,
        include_deleted: bool = False,
    ) -> MemoryRecord:
        access = self._access(access)
        row = self._execute(
            "SELECT * FROM agent_memories WHERE id=?",
            (self._clean_id(memory_id),),
        ).fetchone()
        if row is None or (
            row["lifecycle_status"] == "deleted" and not include_deleted
        ):
            raise MemoryNotFound("memory not found")
        return self._record(row, access=access)

    def list(
        self,
        *,
        access: MemoryReadAccess,
        subject: str | None = None,
        predicate: str | None = None,
        review_status: str | None = None,
        lifecycle_status: str | None = "active",
        include_expired: bool = False,
        include_secret: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        access = self._access(access)
        self._validate_secret_access(access, include_secret)
        clauses: list[str] = []
        params: list[Any] = []
        if subject is not None:
            clauses.append("subject=?")
            params.append(self._clean_text("subject", subject, 200))
        if predicate is not None:
            clauses.append("predicate=?")
            params.append(self._clean_text("predicate", predicate, 200))
        if review_status is not None:
            if review_status not in _REVIEW_STATES:
                raise ProtectedMemoryReadError("invalid review_status")
            clauses.append("review_status=?")
            params.append(review_status)
        if lifecycle_status is not None:
            if lifecycle_status not in _LIFECYCLE_STATES:
                raise ProtectedMemoryReadError("invalid lifecycle_status")
            clauses.append("lifecycle_status=?")
            params.append(lifecycle_status)
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at>?)")
            params.append(time.time())
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(self._limit(limit, 500))
        rows = self._execute(
            "SELECT * FROM agent_memories"
            + where
            + " ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [self._record(row, access=access) for row in rows]

    def history(
        self,
        subject: str,
        predicate: str,
        *,
        access: MemoryReadAccess,
        include_secret: bool = False,
    ) -> list[MemoryRecord]:
        access = self._access(access)
        self._validate_secret_access(access, include_secret)
        clauses = ["subject=?", "predicate=?"]
        params: list[Any] = [
            self._clean_text("subject", subject, 200),
            self._clean_text("predicate", predicate, 200),
        ]
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        rows = self._execute(
            "SELECT * FROM agent_memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at ASC",
            tuple(params),
        ).fetchall()
        return [self._record(row, access=access) for row in rows]

    def search_metadata(
        self,
        query: str,
        *,
        access: MemoryReadAccess,
        confirmed_only: bool = True,
        include_secret: bool = False,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """Search subject/predicate only; values and ciphertext never participate."""

        access = self._access(access)
        self._validate_secret_access(access, include_secret)
        cleaned = self._clean_text("query", query, 300)
        escaped = (
            cleaned.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped.lower()}%"
        clauses = [
            "lifecycle_status='active'",
            "(expires_at IS NULL OR expires_at>?)",
            "(lower(subject) LIKE ? ESCAPE '\\' OR "
            "lower(predicate) LIKE ? ESCAPE '\\')",
        ]
        params: list[Any] = [time.time(), pattern, pattern]
        if confirmed_only:
            clauses.append("review_status='confirmed'")
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        params.append(self._limit(limit, 200))
        rows = self._execute(
            "SELECT * FROM agent_memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [self._record(row, access=access) for row in rows]

    def context_records(
        self,
        *,
        access: MemoryReadAccess,
        subjects: Iterable[str] | None = None,
        include_private: bool = True,
        limit: int = 50,
        max_chars: int = 12_000,
    ) -> list[MemoryRecord]:
        access = self._access(access)
        if access is not MemoryReadAccess.LOCAL_CONTEXT:
            raise ProtectedMemoryReadError(
                "context_records requires local_context access"
            )
        if isinstance(max_chars, bool):
            raise ProtectedMemoryReadError("max_chars must be an integer")
        try:
            budget = int(max_chars)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryReadError("max_chars must be an integer") from exc
        budget = max(0, min(budget, 50_000))
        if budget == 0:
            return []

        clauses = [
            "lifecycle_status='active'",
            "review_status='confirmed'",
            "(expires_at IS NULL OR expires_at>?)",
            "sensitivity!='secret'",
        ]
        params: list[Any] = [time.time()]
        if not include_private:
            clauses.append("sensitivity NOT IN ('private','secret')")
        if subjects is not None:
            selected = [
                self._clean_text("subject", subject, 200) for subject in subjects
            ]
            if not selected:
                return []
            if len(selected) != len(set(selected)):
                raise ProtectedMemoryReadError("subjects must be unique")
            clauses.append("subject IN (" + ",".join("?" for _ in selected) + ")")
            params.extend(selected)
        params.append(self._limit(limit, 200))
        rows = self._execute(
            "SELECT * FROM agent_memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()

        result: list[MemoryRecord] = []
        used = 0
        for row in rows:
            record = self._record(row, access=access)
            size = len(record.subject) + len(record.predicate) + len(record.value)
            if used + size > budget:
                continue
            result.append(record)
            used += size
        return result

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise ProtectedMemoryReadError("memory database path must not be a symlink")
        if not self.path.is_file() or self.path.stat().st_size <= 0:
            raise ProtectedMemoryReadError(
                "memory database must be a non-empty regular file"
            )

    def _validate_store(self) -> ProtectedMemoryReaderStatus:
        columns = {
            str(row[1]) for row in self._execute("PRAGMA table_info(agent_memories)")
        }
        missing = _REQUIRED_COLUMNS - columns
        if missing:
            raise ProtectedMemoryReadError(
                f"protected memory schema is incomplete: {sorted(missing)}"
            )
        migration = self._execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if migration is None:
            raise ProtectedMemoryReadError(
                "protected memory migration receipt is missing"
            )
        if migration["schema"] != MIGRATION_SCHEMA:
            raise ProtectedMemoryReadError(
                "protected memory migration schema mismatch"
            )
        if migration["provider"] != self.codec.provider.provider_id:
            raise ProtectedMemoryReadError("protected memory provider mismatch")
        if migration["key_scope"] != self.codec.provider.key_scope:
            raise ProtectedMemoryReadError("protected memory key scope mismatch")
        if (
            migration["state"] != "completed"
            or int(migration["scrub_completed"]) != 1
        ):
            raise ProtectedMemoryReadError(
                "protected memory migration is not complete"
            )
        if int(self._execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise ProtectedMemoryReadError(
                "protected memory connection is not query-only"
            )

        unsafe_protected = int(
            self._execute(
                "SELECT COUNT(*) FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') AND ("
                "protection_state NOT IN ('protected','redacted') OR "
                "value<>'' OR source_ref IS NOT NULL OR "
                "protection_schema IS NOT ? OR protection_provider IS NOT ? OR "
                "protection_key_scope IS NOT ? OR protection_revision<>?)",
                (
                    ENVELOPE_SCHEMA,
                    self.codec.provider.provider_id,
                    self.codec.provider.key_scope,
                    PROTECTION_REVISION,
                ),
            ).fetchone()[0]
        )
        if unsafe_protected:
            raise ProtectedMemoryReadError(
                "protected memory store contains unsafe private/secret rows"
            )
        unsafe_plain = int(
            self._execute(
                "SELECT COUNT(*) FROM agent_memories "
                "WHERE sensitivity NOT IN ('private','secret') AND ("
                "protection_state<>'plaintext' OR value_protected IS NOT NULL OR "
                "source_ref_protected IS NOT NULL OR "
                "protection_schema IS NOT NULL OR "
                "protection_provider IS NOT NULL OR "
                "protection_key_scope IS NOT NULL OR "
                "protection_fields<>'' OR protection_revision<>0 OR "
                "protection_updated_at IS NOT NULL)"
            ).fetchone()[0]
        )
        if unsafe_plain:
            raise ProtectedMemoryReadError(
                "public/operational memory contains partial protection metadata"
            )
        counts = {
            str(row["protection_state"]): int(row["count"])
            for row in self._execute(
                "SELECT protection_state,COUNT(*) AS count FROM agent_memories "
                "GROUP BY protection_state"
            ).fetchall()
        }
        return ProtectedMemoryReaderStatus(
            schema=MIGRATION_SCHEMA,
            migration_id=MIGRATION_ID,
            provider=str(migration["provider"]),
            key_scope=str(migration["key_scope"]),
            migration_state=str(migration["state"]),
            protected_rows=counts.get("protected", 0),
            redacted_rows=counts.get("redacted", 0),
            public_operational_rows=counts.get("plaintext", 0),
            query_only=True,
        )

    def _record(
        self,
        row: sqlite3.Row,
        *,
        access: MemoryReadAccess,
    ) -> MemoryRecord:
        sensitivity = str(row["sensitivity"])
        if sensitivity in PROTECTED_SENSITIVITIES:
            value, source_ref = self._protected_values(row, access=access)
        else:
            self._validate_plain_row(row)
            if access is MemoryReadAccess.METADATA_ONLY:
                value, source_ref = "[redacted]", None
            elif access is MemoryReadAccess.LOCAL_CONTEXT:
                value, source_ref = str(row["value"]), None
            else:
                value, source_ref = str(row["value"]), row["source_ref"]
        return MemoryRecord(
            id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            value=value,
            kind=str(row["kind"]),
            sensitivity=sensitivity,
            source_type=str(row["source_type"]),
            source_ref=(
                None if source_ref is None else str(source_ref)
            ),
            confidence=float(row["confidence"]),
            review_status=str(row["review_status"]),
            lifecycle_status=str(row["lifecycle_status"]),
            supersedes_id=(
                None
                if row["supersedes_id"] is None
                else str(row["supersedes_id"])
            ),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            expires_at=(
                None if row["expires_at"] is None else float(row["expires_at"])
            ),
            deleted_at=(
                None if row["deleted_at"] is None else float(row["deleted_at"])
            ),
            schema_version=int(row["schema_version"]),
        )

    def _protected_values(
        self,
        row: sqlite3.Row,
        *,
        access: MemoryReadAccess,
    ) -> tuple[str, str | None]:
        self._validate_protected_shape(row)
        if row["protection_state"] == "redacted":
            return "", None
        if access is MemoryReadAccess.METADATA_ONLY:
            return "[redacted]", None
        if (
            row["sensitivity"] == "secret"
            and access is not MemoryReadAccess.LOCAL_MANAGEMENT
        ):
            return "[redacted]", None

        value_envelope = row["value_protected"]
        if not isinstance(value_envelope, str) or not value_envelope:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} value envelope is missing"
            )
        try:
            value = self.codec.unprotect_text(
                value_envelope,
                scope=self._scope(row, "value"),
            )
        except MemoryProtectionError as exc:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} value could not be opened"
            ) from exc

        source_ref: str | None = None
        if (
            access is MemoryReadAccess.LOCAL_MANAGEMENT
            and row["protection_fields"] == "value,source_ref"
        ):
            source_envelope = row["source_ref_protected"]
            if not isinstance(source_envelope, str) or not source_envelope:
                raise ProtectedMemoryReadError(
                    f"protected memory {row['id']} source_ref envelope is missing"
                )
            try:
                source_ref = self.codec.unprotect_text(
                    source_envelope,
                    scope=self._scope(row, "source_ref"),
                )
            except MemoryProtectionError as exc:
                raise ProtectedMemoryReadError(
                    f"protected memory {row['id']} source_ref could not be opened"
                ) from exc
        return value, source_ref

    def _validate_protected_shape(self, row: sqlite3.Row) -> None:
        state = str(row["protection_state"])
        if state not in {"protected", "redacted"}:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} has invalid state"
            )
        if row["value"] != "" or row["source_ref"] is not None:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} retains plaintext"
            )
        if (
            row["protection_schema"] != ENVELOPE_SCHEMA
            or row["protection_provider"] != self.codec.provider.provider_id
            or row["protection_key_scope"] != self.codec.provider.key_scope
            or int(row["protection_revision"]) != PROTECTION_REVISION
        ):
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} metadata mismatch"
            )
        fields = str(row["protection_fields"])
        if state == "redacted":
            if (
                fields != ""
                or row["value_protected"] is not None
                or row["source_ref_protected"] is not None
            ):
                raise ProtectedMemoryReadError(
                    f"redacted memory {row['id']} contains a payload"
                )
            return
        if fields not in {"value", "value,source_ref"}:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} field inventory is invalid"
            )
        if (
            not isinstance(row["value_protected"], str)
            or not row["value_protected"]
        ):
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} value envelope is missing"
            )
        if fields == "value,source_ref":
            if (
                not isinstance(row["source_ref_protected"], str)
                or not row["source_ref_protected"]
            ):
                raise ProtectedMemoryReadError(
                    f"protected memory {row['id']} source_ref envelope is missing"
                )
        elif row["source_ref_protected"] is not None:
            raise ProtectedMemoryReadError(
                f"protected memory {row['id']} has undeclared source_ref envelope"
            )

    @staticmethod
    def _validate_plain_row(row: sqlite3.Row) -> None:
        if row["protection_state"] != "plaintext":
            raise ProtectedMemoryReadError(
                f"unprotected memory {row['id']} has invalid state"
            )
        if any(
            row[name] is not None
            for name in (
                "value_protected",
                "source_ref_protected",
                "protection_schema",
                "protection_provider",
                "protection_key_scope",
                "protection_updated_at",
            )
        ) or row["protection_fields"] != "" or int(row["protection_revision"]) != 0:
            raise ProtectedMemoryReadError(
                f"unprotected memory {row['id']} has protection metadata"
            )

    @staticmethod
    def _scope(row: sqlite3.Row, field: str) -> MemoryProtectionScope:
        return MemoryProtectionScope(
            memory_id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            sensitivity=str(row["sensitivity"]),
            field=field,
            row_schema_version=int(row["schema_version"]),
        )

    def _execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        self._require_open(allow_initializing=True)
        connection = self._conn
        if connection is None:
            raise ProtectedMemoryReadError(
                "protected memory reader has no open connection"
            )
        return connection.execute(sql, parameters)

    def _require_open(self, *, allow_initializing: bool = False) -> None:
        if self._closed:
            raise ProtectedMemoryReadError("protected memory reader is closed")
        if not allow_initializing and self._conn is None:
            raise ProtectedMemoryReadError("protected memory reader is not open")

    def _access(self, value: MemoryReadAccess) -> MemoryReadAccess:
        self._require_open()
        if not isinstance(value, MemoryReadAccess):
            raise ProtectedMemoryReadError(
                "explicit MemoryReadAccess is required"
            )
        return value

    @staticmethod
    def _validate_secret_access(
        access: MemoryReadAccess,
        include_secret: bool,
    ) -> None:
        if include_secret and access is not MemoryReadAccess.LOCAL_MANAGEMENT:
            raise ProtectedMemoryReadError(
                "secret rows require local_management access"
            )

    @staticmethod
    def _clean_id(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise ProtectedMemoryReadError("invalid memory id")
        return value.strip()

    @staticmethod
    def _clean_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise ProtectedMemoryReadError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned:
            raise ProtectedMemoryReadError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise ProtectedMemoryReadError(
                f"{name} exceeds {maximum} characters"
            )
        return cleaned

    @staticmethod
    def _limit(value: Any, maximum: int) -> int:
        if isinstance(value, bool):
            raise ProtectedMemoryReadError("limit must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryReadError("limit must be an integer") from exc
        return max(1, min(parsed, maximum))
