from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .memory import (
    KINDS,
    REVIEW_STATES,
    SOURCE_TYPES,
    MemoryConflict,
    MemoryNotFound,
    MemoryRecord,
    MemoryStoreError,
)
from .memory_protected_reader import ProtectedMemoryReader
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


class ProtectedMemoryWriteError(MemoryStoreError):
    """A protected memory write cannot complete without exposing plaintext."""


class MemoryWriteAccess(str, Enum):
    LOCAL_MANAGEMENT = "local_management"


class ProtectedMemoryWriter:
    """Explicit private/secret writer for a completed protected store.

    The writer is dormant and not wired into Agent 3 startup or HTTP routes. It
    never writes a sensitive value or source reference to plaintext columns. New
    rows, corrections and tombstones are committed atomically under an explicit
    local-management access token.
    """

    def __init__(
        self,
        path: str | Path,
        codec: MemoryProtectionCodec,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        busy_timeout_ms: int = 5_000,
    ):
        self.path = Path(path)
        self.codec = codec
        self.clock = clock
        self.id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))
        self._lock = threading.RLock()
        self._closed = False
        self._conn: sqlite3.Connection | None = None
        self._validate_path()

        # Reuse the exact read boundary before opening a writable connection.
        with ProtectedMemoryReader(self.path, self.codec):
            pass
        try:
            self._conn = sqlite3.connect(
                self.path,
                check_same_thread=False,
                timeout=self.busy_timeout_ms / 1000.0,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA secure_delete=ON")
            mode = str(self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
            if mode.lower() != "wal":
                raise ProtectedMemoryWriteError(
                    "protected memory writer requires WAL journal mode"
                )
            self._validate_migration()
        except (sqlite3.Error, MemoryProtectionError, ProtectedMemoryWriteError):
            self._close_connection()
            raise

    def close(self) -> None:
        with self._lock:
            self._close_connection()
            self._closed = True

    def _close_connection(self) -> None:
        connection = self._conn
        self._conn = None
        if connection is not None:
            connection.close()

    def __enter__(self) -> "ProtectedMemoryWriter":
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def create(
        self,
        *,
        access: MemoryWriteAccess,
        subject: str,
        predicate: str,
        value: str,
        kind: str = "fact",
        sensitivity: str = "private",
        source_type: str = "user_explicit",
        source_ref: str | None = None,
        confidence: float = 1.0,
        review_status: str | None = None,
        expires_at: float | None = None,
    ) -> MemoryRecord:
        self._access(access)
        fields = self._validate_fields(
            subject=subject,
            predicate=predicate,
            value=value,
            kind=kind,
            sensitivity=sensitivity,
            source_type=source_type,
            source_ref=source_ref,
            confidence=confidence,
            review_status=review_status,
            expires_at=expires_at,
        )
        memory_id = self._new_id()
        now = self.clock()
        value_envelope, source_envelope, protected_fields = self._protect_fields(
            memory_id=memory_id,
            subject=fields["subject"],
            predicate=fields["predicate"],
            sensitivity=fields["sensitivity"],
            value=fields["value"],
            source_ref=fields["source_ref"],
            schema_version=1,
        )
        with self._transaction():
            self._validate_migration()
            self._insert_locked(
                memory_id=memory_id,
                fields=fields,
                value_envelope=value_envelope,
                source_envelope=source_envelope,
                protected_fields=protected_fields,
                now=now,
                supersedes_id=None,
            )
        return self._result_record(
            memory_id=memory_id,
            fields=fields,
            now=now,
            lifecycle_status="active",
            supersedes_id=None,
            deleted_at=None,
        )

    def correct(
        self,
        memory_id: str,
        *,
        access: MemoryWriteAccess,
        expected_updated_at: float,
        value: str,
        source_ref: str | None = None,
        sensitivity: str | None = None,
        confidence: float = 1.0,
        expires_at: float | None = None,
    ) -> MemoryRecord:
        self._access(access)
        old_id = self._clean_id(memory_id)
        expected = self._timestamp("expected_updated_at", expected_updated_at)
        now = self.clock()
        new_id = self._new_id()
        with self._transaction():
            self._validate_migration()
            old = self._row_locked(old_id)
            if old is None or old["lifecycle_status"] != "active":
                raise MemoryNotFound("active memory not found")
            self._validate_protected_row(old)
            if float(old["updated_at"]) != expected:
                raise MemoryConflict("memory changed before protected correction")
            fields = self._validate_fields(
                subject=str(old["subject"]),
                predicate=str(old["predicate"]),
                value=value,
                kind=str(old["kind"]),
                sensitivity=sensitivity or str(old["sensitivity"]),
                source_type="user_explicit",
                source_ref=source_ref,
                confidence=confidence,
                review_status="confirmed",
                expires_at=expires_at,
            )
            value_envelope, source_envelope, protected_fields = self._protect_fields(
                memory_id=new_id,
                subject=fields["subject"],
                predicate=fields["predicate"],
                sensitivity=fields["sensitivity"],
                value=fields["value"],
                source_ref=fields["source_ref"],
                schema_version=1,
            )
            self._insert_locked(
                memory_id=new_id,
                fields=fields,
                value_envelope=value_envelope,
                source_envelope=source_envelope,
                protected_fields=protected_fields,
                now=now,
                supersedes_id=old_id,
            )
            changed = self._execute(
                "UPDATE agent_memories SET lifecycle_status='superseded',"
                "updated_at=? WHERE id=? AND lifecycle_status='active' "
                "AND updated_at=?",
                (now, old_id, expected),
            ).rowcount
            if changed != 1:
                raise MemoryConflict(
                    "memory changed while protected correction was committed"
                )
        return self._result_record(
            memory_id=new_id,
            fields=fields,
            now=now,
            lifecycle_status="active",
            supersedes_id=old_id,
            deleted_at=None,
        )

    def delete(
        self,
        memory_id: str,
        *,
        access: MemoryWriteAccess,
        expected_updated_at: float,
    ) -> MemoryRecord:
        self._access(access)
        cleaned_id = self._clean_id(memory_id)
        expected = self._timestamp("expected_updated_at", expected_updated_at)
        now = self.clock()
        with self._transaction():
            self._validate_migration()
            row = self._row_locked(cleaned_id)
            if row is None or row["lifecycle_status"] == "deleted":
                raise MemoryNotFound("memory not found")
            self._validate_protected_row(row)
            if float(row["updated_at"]) != expected:
                raise MemoryConflict("memory changed before protected delete")
            changed = self._execute(
                "UPDATE agent_memories SET value='',source_ref=NULL,"
                "value_protected=NULL,source_ref_protected=NULL,"
                "review_status='rejected',lifecycle_status='deleted',"
                "deleted_at=?,updated_at=?,protection_state='redacted',"
                "protection_fields='',protection_updated_at=? "
                "WHERE id=? AND lifecycle_status!='deleted' AND updated_at=?",
                (now, now, now, cleaned_id, expected),
            ).rowcount
            if changed != 1:
                raise MemoryConflict("memory changed while protected delete committed")
            deleted = self._row_locked(cleaned_id)
            if deleted is None:
                raise ProtectedMemoryWriteError(
                    "protected delete lost the lifecycle tombstone"
                )
            self._validate_protected_row(deleted)
        return MemoryRecord(
            id=cleaned_id,
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            value="",
            kind=str(row["kind"]),
            sensitivity=str(row["sensitivity"]),
            source_type=str(row["source_type"]),
            source_ref=None,
            confidence=float(row["confidence"]),
            review_status="rejected",
            lifecycle_status="deleted",
            supersedes_id=(
                None if row["supersedes_id"] is None else str(row["supersedes_id"])
            ),
            created_at=float(row["created_at"]),
            updated_at=now,
            expires_at=(
                None if row["expires_at"] is None else float(row["expires_at"])
            ),
            deleted_at=now,
            schema_version=int(row["schema_version"]),
        )

    def _insert_locked(
        self,
        *,
        memory_id: str,
        fields: dict[str, Any],
        value_envelope: str,
        source_envelope: str | None,
        protected_fields: str,
        now: float,
        supersedes_id: str | None,
    ) -> None:
        try:
            self._execute(
                "INSERT INTO agent_memories("
                "id,subject,predicate,value,kind,sensitivity,source_type,"
                "source_ref,confidence,review_status,lifecycle_status,"
                "supersedes_id,created_at,updated_at,expires_at,deleted_at,"
                "schema_version,value_protected,source_ref_protected,"
                "protection_schema,protection_provider,protection_key_scope,"
                "protection_state,protection_fields,protection_revision,"
                "protection_updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    memory_id,
                    fields["subject"],
                    fields["predicate"],
                    "",
                    fields["kind"],
                    fields["sensitivity"],
                    fields["source_type"],
                    None,
                    fields["confidence"],
                    fields["review_status"],
                    "active",
                    supersedes_id,
                    now,
                    now,
                    fields["expires_at"],
                    None,
                    1,
                    value_envelope,
                    source_envelope,
                    ENVELOPE_SCHEMA,
                    self.codec.provider.provider_id,
                    self.codec.provider.key_scope,
                    "protected",
                    protected_fields,
                    PROTECTION_REVISION,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise MemoryConflict("protected memory id already exists") from exc
        row = self._row_locked(memory_id)
        if row is None:
            raise ProtectedMemoryWriteError("protected insert did not persist")
        self._validate_protected_row(row)

    def _protect_fields(
        self,
        *,
        memory_id: str,
        subject: str,
        predicate: str,
        sensitivity: str,
        value: str,
        source_ref: str | None,
        schema_version: int,
    ) -> tuple[str, str | None, str]:
        try:
            value_envelope = self.codec.protect_text(
                value,
                scope=MemoryProtectionScope(
                    memory_id=memory_id,
                    subject=subject,
                    predicate=predicate,
                    sensitivity=sensitivity,
                    field="value",
                    row_schema_version=schema_version,
                ),
            )
            source_envelope = None
            fields = "value"
            if source_ref is not None:
                source_envelope = self.codec.protect_text(
                    source_ref,
                    scope=MemoryProtectionScope(
                        memory_id=memory_id,
                        subject=subject,
                        predicate=predicate,
                        sensitivity=sensitivity,
                        field="source_ref",
                        row_schema_version=schema_version,
                    ),
                )
                fields = "value,source_ref"
            return value_envelope, source_envelope, fields
        except MemoryProtectionError as exc:
            raise ProtectedMemoryWriteError(
                "protected memory fields could not be encrypted"
            ) from exc

    def _validate_migration(self) -> None:
        row = self._execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryWriteError(
                "protected memory migration receipt is missing"
            )
        if (
            row["schema"] != MIGRATION_SCHEMA
            or row["provider"] != self.codec.provider.provider_id
            or row["key_scope"] != self.codec.provider.key_scope
            or row["state"] != "completed"
            or int(row["scrub_completed"]) != 1
        ):
            raise ProtectedMemoryWriteError(
                "protected memory migration receipt is not write-eligible"
            )

    def _validate_protected_row(self, row: sqlite3.Row) -> None:
        if row["sensitivity"] not in PROTECTED_SENSITIVITIES:
            raise ProtectedMemoryWriteError(
                "protected writer cannot mutate public/operational memory"
            )
        state = str(row["protection_state"])
        if state not in {"protected", "redacted"}:
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} has invalid state"
            )
        if row["value"] != "" or row["source_ref"] is not None:
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} retains plaintext"
            )
        if (
            row["protection_schema"] != ENVELOPE_SCHEMA
            or row["protection_provider"] != self.codec.provider.provider_id
            or row["protection_key_scope"] != self.codec.provider.key_scope
            or int(row["protection_revision"]) != PROTECTION_REVISION
        ):
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} metadata mismatch"
            )
        fields = str(row["protection_fields"])
        if state == "redacted":
            if (
                fields != ""
                or row["value_protected"] is not None
                or row["source_ref_protected"] is not None
            ):
                raise ProtectedMemoryWriteError(
                    f"redacted memory {row['id']} retains a payload"
                )
            return
        if fields not in {"value", "value,source_ref"}:
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} field inventory is invalid"
            )
        if not isinstance(row["value_protected"], str) or not row["value_protected"]:
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} value envelope is missing"
            )
        if fields == "value,source_ref":
            if (
                not isinstance(row["source_ref_protected"], str)
                or not row["source_ref_protected"]
            ):
                raise ProtectedMemoryWriteError(
                    f"protected memory {row['id']} source_ref envelope is missing"
                )
        elif row["source_ref_protected"] is not None:
            raise ProtectedMemoryWriteError(
                f"protected memory {row['id']} has undeclared source_ref payload"
            )

    def _validate_fields(
        self,
        *,
        subject: Any,
        predicate: Any,
        value: Any,
        kind: Any,
        sensitivity: Any,
        source_type: Any,
        source_ref: Any,
        confidence: Any,
        review_status: Any,
        expires_at: Any,
    ) -> dict[str, Any]:
        selected_sensitivity = self._choice(
            "sensitivity", sensitivity, PROTECTED_SENSITIVITIES
        )
        selected_source = self._choice("source_type", source_type, SOURCE_TYPES)
        if review_status is None:
            selected_review = (
                "confirmed" if selected_source == "user_explicit" else "pending"
            )
        else:
            selected_review = self._choice(
                "review_status", review_status, REVIEW_STATES
            )
        try:
            selected_confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryWriteError("confidence must be numeric") from exc
        if not 0.0 <= selected_confidence <= 1.0:
            raise ProtectedMemoryWriteError("confidence must be between 0 and 1")
        selected_expiry = None
        if expires_at is not None:
            selected_expiry = self._timestamp("expires_at", expires_at)
        return {
            "subject": self._clean_text("subject", subject, 200),
            "predicate": self._clean_text("predicate", predicate, 200),
            "value": self._clean_text("value", value, 50_000),
            "kind": self._choice("kind", kind, KINDS),
            "sensitivity": selected_sensitivity,
            "source_type": selected_source,
            "source_ref": (
                None
                if source_ref is None
                else self._clean_text("source_ref", source_ref, 1_000)
            ),
            "confidence": selected_confidence,
            "review_status": selected_review,
            "expires_at": selected_expiry,
        }

    def _result_record(
        self,
        *,
        memory_id: str,
        fields: dict[str, Any],
        now: float,
        lifecycle_status: str,
        supersedes_id: str | None,
        deleted_at: float | None,
    ) -> MemoryRecord:
        return MemoryRecord(
            id=memory_id,
            subject=fields["subject"],
            predicate=fields["predicate"],
            value=fields["value"],
            kind=fields["kind"],
            sensitivity=fields["sensitivity"],
            source_type=fields["source_type"],
            source_ref=fields["source_ref"],
            confidence=fields["confidence"],
            review_status=fields["review_status"],
            lifecycle_status=lifecycle_status,
            supersedes_id=supersedes_id,
            created_at=now,
            updated_at=now,
            expires_at=fields["expires_at"],
            deleted_at=deleted_at,
            schema_version=1,
        )

    def _row_locked(self, memory_id: str) -> sqlite3.Row | None:
        return self._execute(
            "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
        ).fetchone()

    def _new_id(self) -> str:
        return self._clean_id(self.id_factory())

    def _access(self, value: MemoryWriteAccess) -> None:
        self._require_open()
        if value is not MemoryWriteAccess.LOCAL_MANAGEMENT:
            raise ProtectedMemoryWriteError(
                "protected writes require explicit local_management access"
            )

    def _execute(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> sqlite3.Cursor:
        connection = self._conn
        if connection is None:
            raise ProtectedMemoryWriteError(
                "protected memory writer has no open connection"
            )
        return connection.execute(sql, parameters)

    def _require_open(self) -> None:
        if self._closed or self._conn is None:
            raise ProtectedMemoryWriteError("protected memory writer is closed")

    def _transaction(self):
        writer = self

        class Transaction:
            def __enter__(self_inner):
                writer._lock.acquire()
                writer._require_open()
                try:
                    writer._execute("BEGIN IMMEDIATE")
                except Exception:
                    writer._lock.release()
                    raise
                return self_inner

            def __exit__(self_inner, exc_type, exc, _tb):
                try:
                    if exc_type is None:
                        writer._execute("COMMIT")
                    else:
                        writer._execute("ROLLBACK")
                finally:
                    writer._lock.release()
                return False

        return Transaction()

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise ProtectedMemoryWriteError(
                "memory database path must not be a symlink"
            )
        if not self.path.is_file() or self.path.stat().st_size <= 0:
            raise ProtectedMemoryWriteError(
                "memory database must be a non-empty regular file"
            )

    @staticmethod
    def _clean_id(value: Any) -> str:
        if not isinstance(value, str):
            raise ProtectedMemoryWriteError("memory id must be text")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 100 or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in cleaned
        ):
            raise ProtectedMemoryWriteError("memory id is invalid")
        return cleaned

    @staticmethod
    def _clean_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise ProtectedMemoryWriteError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned:
            raise ProtectedMemoryWriteError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise ProtectedMemoryWriteError(
                f"{name} exceeds {maximum} characters"
            )
        return cleaned

    @staticmethod
    def _choice(name: str, value: Any, allowed: Any) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise ProtectedMemoryWriteError(f"invalid {name}")
        return value

    @staticmethod
    def _timestamp(name: str, value: Any) -> float:
        if isinstance(value, bool):
            raise ProtectedMemoryWriteError(f"{name} must be numeric")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryWriteError(f"{name} must be numeric") from exc
        if parsed < 0:
            raise ProtectedMemoryWriteError(f"{name} must be non-negative")
        return parsed
