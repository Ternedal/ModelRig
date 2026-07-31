from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .memory_protection import (
    ENVELOPE_SCHEMA,
    MemoryProtectionCodec,
    MemoryProtectionError,
    MemoryProtectionScope,
    PROTECTED_SENSITIVITIES,
)


MIGRATION_SCHEMA = "kaliv-agent3-memory-protection-migration/v1"
MIGRATION_ID = "agent3-memory-private-secret-v1"
MIGRATION_STATES = frozenset({"running", "scrubbing", "completed"})
ROW_STATES = frozenset({"plaintext", "protected", "redacted"})
PROTECTION_REVISION = 1

_ADDED_COLUMNS: dict[str, str] = {
    "value_protected": "TEXT",
    "source_ref_protected": "TEXT",
    "protection_schema": "TEXT",
    "protection_provider": "TEXT",
    "protection_key_scope": "TEXT",
    "protection_state": "TEXT NOT NULL DEFAULT 'plaintext'",
    "protection_fields": "TEXT NOT NULL DEFAULT ''",
    "protection_revision": "INTEGER NOT NULL DEFAULT 0",
    "protection_updated_at": "REAL",
}
_REQUIRED_BASE_COLUMNS = {
    "id",
    "subject",
    "predicate",
    "value",
    "sensitivity",
    "source_ref",
    "lifecycle_status",
    "schema_version",
}


class MemoryProtectionMigrationError(RuntimeError):
    """The offline memory migration cannot proceed without risking plaintext."""


@dataclass(frozen=True)
class MemoryProtectionMigrationSummary:
    schema: str
    migration_id: str
    provider: str
    key_scope: str
    state: str
    protected_total: int
    rows_protected: int
    rows_redacted: int
    rows_remaining_plaintext: int
    source_refs_protected: int
    batch_commits: int
    scrub_completed: bool

    @property
    def complete(self) -> bool:
        return (
            self.state == "completed"
            and self.rows_remaining_plaintext == 0
            and self.scrub_completed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "migration_id": self.migration_id,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "state": self.state,
            "protected_total": self.protected_total,
            "rows_protected": self.rows_protected,
            "rows_redacted": self.rows_redacted,
            "rows_remaining_plaintext": self.rows_remaining_plaintext,
            "source_refs_protected": self.source_refs_protected,
            "batch_commits": self.batch_commits,
            "scrub_completed": self.scrub_completed,
            "complete": self.complete,
            "production_activation": False,
        }


class MemoryProtectionMigrator:
    """Resumable offline migration for private/secret memory fields.

    The migrator is not imported by ``MemoryStore`` and never runs at startup. A
    caller must explicitly stop the worker, open the exact SQLite file and supply
    a protection codec. Each row commits atomically. Completion is not reported
    until every protected row validates, plaintext columns are empty, SQLite has
    run with ``secure_delete=ON``, the database has been vacuumed and WAL has been
    checkpointed/truncated.
    """

    def __init__(
        self,
        path: str | Path,
        codec: MemoryProtectionCodec,
        *,
        clock: Callable[[], float] = time.time,
        busy_timeout_ms: int = 5_000,
    ):
        self.path = Path(path)
        self.codec = codec
        self.clock = clock
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))
        self._validate_path()

    def migrate(
        self,
        *,
        batch_limit: int | None = None,
        finalize: bool = True,
    ) -> MemoryProtectionMigrationSummary:
        if batch_limit is not None:
            if isinstance(batch_limit, bool) or not isinstance(batch_limit, int):
                raise MemoryProtectionMigrationError("batch_limit must be an integer")
            if batch_limit < 1:
                raise MemoryProtectionMigrationError("batch_limit must be at least one")

        conn = self._connect()
        try:
            self._configure_offline_connection(conn)
            self._ensure_schema(conn)
            self._ensure_migration_record(conn)
            self._validate_unprotected_classes(conn)

            migrated = 0
            rows = conn.execute(
                "SELECT id FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') ORDER BY created_at,id"
            ).fetchall()
            for row in rows:
                current = self._row(conn, str(row["id"]))
                state = str(current["protection_state"])
                if state in {"protected", "redacted"}:
                    self._validate_protected_row(current)
                    continue
                if state != "plaintext":
                    raise MemoryProtectionMigrationError(
                        f"memory row {current['id']} has unknown protection state"
                    )
                if batch_limit is not None and migrated >= batch_limit:
                    break
                self._migrate_one(conn, str(current["id"]))
                migrated += 1

            summary = self._refresh_summary(conn)
            if finalize and summary.rows_remaining_plaintext == 0:
                self._finalize(conn)
                summary = self._refresh_summary(conn)
            return summary
        except (sqlite3.Error, MemoryProtectionError) as exc:
            if isinstance(exc, MemoryProtectionMigrationError):
                raise
            raise MemoryProtectionMigrationError(
                f"memory protection migration failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            conn.close()

    def inspect(self) -> MemoryProtectionMigrationSummary:
        conn = self._connect()
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._require_schema(conn)
            self._ensure_migration_record(conn, create=False)
            self._validate_unprotected_classes(conn)
            for row in conn.execute(
                "SELECT * FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') ORDER BY id"
            ).fetchall():
                self._validate_protected_row(row, allow_plaintext=True)
            return self._refresh_summary(conn, mutate=False)
        except (sqlite3.Error, MemoryProtectionError) as exc:
            if isinstance(exc, MemoryProtectionMigrationError):
                raise
            raise MemoryProtectionMigrationError(
                f"memory protection inspection failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            conn.close()

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise MemoryProtectionMigrationError("memory database path must not be a symlink")
        if not self.path.is_file():
            raise MemoryProtectionMigrationError("memory database must be a regular file")
        if self.path.stat().st_size <= 0:
            raise MemoryProtectionMigrationError("memory database is empty")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _configure_offline_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        try:
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.OperationalError as exc:
            raise MemoryProtectionMigrationError(
                "memory database WAL cannot be checkpointed; stop all worker processes"
            ) from exc
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise MemoryProtectionMigrationError(
                "memory database WAL is busy; stop all worker processes"
            )
        mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        if mode != "delete":
            raise MemoryProtectionMigrationError(
                "memory database could not enter offline DELETE journal mode"
            )
        lock_mode = str(conn.execute("PRAGMA locking_mode=EXCLUSIVE").fetchone()[0]).lower()
        if lock_mode != "exclusive":
            raise MemoryProtectionMigrationError(
                "memory database could not enter exclusive migration mode"
            )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        existing = self._table_columns(conn, "agent_memories")
        if not existing:
            raise MemoryProtectionMigrationError("agent_memories table is missing")
        missing_base = _REQUIRED_BASE_COLUMNS - set(existing)
        if missing_base:
            raise MemoryProtectionMigrationError(
                f"agent_memories base schema is incomplete: {sorted(missing_base)}"
            )

        conn.execute("BEGIN EXCLUSIVE")
        try:
            for name, declaration in _ADDED_COLUMNS.items():
                if name not in existing:
                    conn.execute(
                        f"ALTER TABLE agent_memories ADD COLUMN {name} {declaration}"
                    )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_memory_protection_migrations (
                    id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    key_scope TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    protected_total INTEGER NOT NULL DEFAULT 0,
                    rows_protected INTEGER NOT NULL DEFAULT 0,
                    rows_redacted INTEGER NOT NULL DEFAULT 0,
                    rows_remaining_plaintext INTEGER NOT NULL DEFAULT 0,
                    source_refs_protected INTEGER NOT NULL DEFAULT 0,
                    batch_commits INTEGER NOT NULL DEFAULT 0,
                    scrub_completed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        self._require_schema(conn)

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        existing = self._table_columns(conn, "agent_memories")
        required = _REQUIRED_BASE_COLUMNS | set(_ADDED_COLUMNS)
        missing = required - set(existing)
        if missing:
            raise MemoryProtectionMigrationError(
                f"memory protection columns are missing: {sorted(missing)}"
            )
        migration_columns = self._table_columns(
            conn, "agent_memory_protection_migrations"
        )
        expected_migration = {
            "id",
            "schema",
            "provider",
            "key_scope",
            "state",
            "started_at",
            "updated_at",
            "completed_at",
            "protected_total",
            "rows_protected",
            "rows_redacted",
            "rows_remaining_plaintext",
            "source_refs_protected",
            "batch_commits",
            "scrub_completed",
        }
        if set(migration_columns) != expected_migration:
            raise MemoryProtectionMigrationError(
                "memory protection migration table schema mismatch"
            )

    def _ensure_migration_record(
        self, conn: sqlite3.Connection, *, create: bool = True
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if row is None:
            if not create:
                raise MemoryProtectionMigrationError(
                    "memory protection migration record is missing"
                )
            now = self.clock()
            conn.execute("BEGIN EXCLUSIVE")
            try:
                conn.execute(
                    "INSERT INTO agent_memory_protection_migrations("
                    "id,schema,provider,key_scope,state,started_at,updated_at,"
                    "protected_total,rows_protected,rows_redacted,"
                    "rows_remaining_plaintext,source_refs_protected,batch_commits,"
                    "scrub_completed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        MIGRATION_ID,
                        MIGRATION_SCHEMA,
                        self.codec.provider.provider_id,
                        self.codec.provider.key_scope,
                        "running",
                        now,
                        now,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            row = conn.execute(
                "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
                (MIGRATION_ID,),
            ).fetchone()
        if row is None:
            raise MemoryProtectionMigrationError(
                "memory protection migration record could not be created"
            )
        if row["schema"] != MIGRATION_SCHEMA:
            raise MemoryProtectionMigrationError("memory migration schema mismatch")
        if row["provider"] != self.codec.provider.provider_id:
            raise MemoryProtectionMigrationError("memory migration provider mismatch")
        if row["key_scope"] != self.codec.provider.key_scope:
            raise MemoryProtectionMigrationError("memory migration key scope mismatch")
        if row["state"] not in MIGRATION_STATES:
            raise MemoryProtectionMigrationError("memory migration state is invalid")
        if int(row["scrub_completed"]) not in {0, 1}:
            raise MemoryProtectionMigrationError(
                "memory migration scrub state is invalid"
            )
        return row

    def _validate_unprotected_classes(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT * FROM agent_memories "
            "WHERE sensitivity NOT IN ('private','secret')"
        ).fetchall()
        for row in rows:
            if row["protection_state"] != "plaintext":
                raise MemoryProtectionMigrationError(
                    f"unprotected memory row {row['id']} has protection metadata"
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
                raise MemoryProtectionMigrationError(
                    f"unprotected memory row {row['id']} has partial protection metadata"
                )

    def _migrate_one(self, conn: sqlite3.Connection, memory_id: str) -> None:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            row = self._row(conn, memory_id)
            if row["sensitivity"] not in PROTECTED_SENSITIVITIES:
                raise MemoryProtectionMigrationError(
                    f"memory row {memory_id} is not a protected sensitivity"
                )
            if row["protection_state"] != "plaintext":
                self._validate_protected_row(row)
                conn.commit()
                return
            self._validate_plaintext_row(row)

            now = self.clock()
            value = str(row["value"])
            source_ref = row["source_ref"]
            if row["lifecycle_status"] == "deleted" or value == "":
                conn.execute(
                    "UPDATE agent_memories SET value='',source_ref=NULL,"
                    "value_protected=NULL,source_ref_protected=NULL,"
                    "protection_schema=?,protection_provider=?,protection_key_scope=?,"
                    "protection_state='redacted',protection_fields='',"
                    "protection_revision=?,protection_updated_at=? WHERE id=?",
                    (
                        ENVELOPE_SCHEMA,
                        self.codec.provider.provider_id,
                        self.codec.provider.key_scope,
                        PROTECTION_REVISION,
                        now,
                        memory_id,
                    ),
                )
            else:
                value_scope = self._scope(row, "value")
                value_envelope = self.codec.protect_text(value, scope=value_scope)
                source_envelope = None
                fields = ["value"]
                if source_ref is not None:
                    if not isinstance(source_ref, str) or source_ref == "":
                        raise MemoryProtectionMigrationError(
                            f"memory row {memory_id} source_ref is malformed"
                        )
                    source_envelope = self.codec.protect_text(
                        source_ref, scope=self._scope(row, "source_ref")
                    )
                    fields.append("source_ref")
                conn.execute(
                    "UPDATE agent_memories SET value='',source_ref=NULL,"
                    "value_protected=?,source_ref_protected=?,"
                    "protection_schema=?,protection_provider=?,protection_key_scope=?,"
                    "protection_state='protected',protection_fields=?,"
                    "protection_revision=?,protection_updated_at=? WHERE id=?",
                    (
                        value_envelope,
                        source_envelope,
                        ENVELOPE_SCHEMA,
                        self.codec.provider.provider_id,
                        self.codec.provider.key_scope,
                        ",".join(fields),
                        PROTECTION_REVISION,
                        now,
                        memory_id,
                    ),
                )
            conn.execute(
                "UPDATE agent_memory_protection_migrations "
                "SET state='running',updated_at=?,batch_commits=batch_commits+1,"
                "scrub_completed=0,completed_at=NULL WHERE id=?",
                (now, MIGRATION_ID),
            )
            migrated = self._row(conn, memory_id)
            self._validate_protected_row(migrated)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _validate_plaintext_row(self, row: sqlite3.Row) -> None:
        if row["protection_state"] != "plaintext":
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} is not plaintext"
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
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} has partial protection metadata"
            )
        if row["lifecycle_status"] != "deleted" and not isinstance(row["value"], str):
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} plaintext value is malformed"
            )

    def _validate_protected_row(
        self, row: sqlite3.Row, *, allow_plaintext: bool = False
    ) -> None:
        state = str(row["protection_state"])
        if state == "plaintext":
            self._validate_plaintext_row(row)
            if allow_plaintext:
                return
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} is still plaintext"
            )
        if state not in {"protected", "redacted"}:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} has unknown protection state"
            )
        if row["sensitivity"] not in PROTECTED_SENSITIVITIES:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} protection sensitivity mismatch"
            )
        if row["value"] != "" or row["source_ref"] is not None:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} retains readable plaintext"
            )
        if (
            row["protection_schema"] != ENVELOPE_SCHEMA
            or row["protection_provider"] != self.codec.provider.provider_id
            or row["protection_key_scope"] != self.codec.provider.key_scope
            or int(row["protection_revision"]) != PROTECTION_REVISION
            or not isinstance(row["protection_updated_at"], (int, float))
        ):
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} protection metadata mismatch"
            )

        if state == "redacted":
            if (
                row["value_protected"] is not None
                or row["source_ref_protected"] is not None
                or row["protection_fields"] != ""
            ):
                raise MemoryProtectionMigrationError(
                    f"redacted memory row {row['id']} contains protected payloads"
                )
            return

        fields = str(row["protection_fields"])
        if fields not in {"value", "value,source_ref"}:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} protected field inventory is invalid"
            )
        value_envelope = row["value_protected"]
        if not isinstance(value_envelope, str) or not value_envelope:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} value envelope is missing"
            )
        opened_value = self.codec.unprotect_text(
            value_envelope, scope=self._scope(row, "value")
        )
        if not opened_value:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} value envelope opened empty"
            )
        del opened_value

        source_envelope = row["source_ref_protected"]
        if fields == "value,source_ref":
            if not isinstance(source_envelope, str) or not source_envelope:
                raise MemoryProtectionMigrationError(
                    f"memory row {row['id']} source_ref envelope is missing"
                )
            opened_source = self.codec.unprotect_text(
                source_envelope, scope=self._scope(row, "source_ref")
            )
            if not opened_source:
                raise MemoryProtectionMigrationError(
                    f"memory row {row['id']} source_ref envelope opened empty"
                )
            del opened_source
        elif source_envelope is not None:
            raise MemoryProtectionMigrationError(
                f"memory row {row['id']} has an undeclared source_ref envelope"
            )

    def _scope(self, row: sqlite3.Row, field: str) -> MemoryProtectionScope:
        return MemoryProtectionScope(
            memory_id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            sensitivity=str(row["sensitivity"]),
            field=field,
            row_schema_version=int(row["schema_version"]),
        )

    def _refresh_summary(
        self, conn: sqlite3.Connection, *, mutate: bool = True
    ) -> MemoryProtectionMigrationSummary:
        states = {
            str(row["protection_state"]): int(row["count"])
            for row in conn.execute(
                "SELECT protection_state,COUNT(*) AS count FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') GROUP BY protection_state"
            ).fetchall()
        }
        unknown = set(states) - ROW_STATES
        if unknown:
            raise MemoryProtectionMigrationError(
                f"unknown memory protection row states: {sorted(unknown)}"
            )
        total = sum(states.values())
        protected = states.get("protected", 0)
        redacted = states.get("redacted", 0)
        remaining = states.get("plaintext", 0)
        source_refs = int(
            conn.execute(
                "SELECT COUNT(*) FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') "
                "AND protection_state='protected' "
                "AND protection_fields='value,source_ref'"
            ).fetchone()[0]
        )
        if mutate:
            now = self.clock()
            conn.execute("BEGIN EXCLUSIVE")
            try:
                conn.execute(
                    "UPDATE agent_memory_protection_migrations SET "
                    "updated_at=?,protected_total=?,rows_protected=?,rows_redacted=?,"
                    "rows_remaining_plaintext=?,source_refs_protected=? WHERE id=?",
                    (
                        now,
                        total,
                        protected,
                        redacted,
                        remaining,
                        source_refs,
                        MIGRATION_ID,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        row = self._ensure_migration_record(conn, create=False)
        return MemoryProtectionMigrationSummary(
            schema=MIGRATION_SCHEMA,
            migration_id=MIGRATION_ID,
            provider=str(row["provider"]),
            key_scope=str(row["key_scope"]),
            state=str(row["state"]),
            protected_total=total,
            rows_protected=protected,
            rows_redacted=redacted,
            rows_remaining_plaintext=remaining,
            source_refs_protected=source_refs,
            batch_commits=int(row["batch_commits"]),
            scrub_completed=bool(row["scrub_completed"]),
        )

    def _finalize(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT * FROM agent_memories "
            "WHERE sensitivity IN ('private','secret') ORDER BY id"
        ).fetchall()
        for row in rows:
            self._validate_protected_row(row)
        if conn.execute(
            "SELECT COUNT(*) FROM agent_memories "
            "WHERE sensitivity IN ('private','secret') "
            "AND (value<>'' OR source_ref IS NOT NULL OR protection_state='plaintext')"
        ).fetchone()[0] != 0:
            raise MemoryProtectionMigrationError(
                "protected memory plaintext remains before final scrub"
            )

        now = self.clock()
        conn.execute("BEGIN EXCLUSIVE")
        try:
            conn.execute(
                "UPDATE agent_memory_protection_migrations SET "
                "state='scrubbing',updated_at=?,scrub_completed=0,completed_at=NULL "
                "WHERE id=?",
                (now, MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("VACUUM")
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise MemoryProtectionMigrationError(
                "memory database could not restore WAL journal mode"
            )

        completed = self.clock()
        conn.execute("BEGIN EXCLUSIVE")
        try:
            conn.execute(
                "UPDATE agent_memory_protection_migrations SET "
                "state='completed',updated_at=?,completed_at=?,scrub_completed=1 "
                "WHERE id=?",
                (completed, completed, MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise MemoryProtectionMigrationError(
                "memory database WAL could not be truncated after migration"
            )
        for row in conn.execute(
            "SELECT * FROM agent_memories "
            "WHERE sensitivity IN ('private','secret') ORDER BY id"
        ).fetchall():
            self._validate_protected_row(row)

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
        return {
            str(row["name"]): row
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @staticmethod
    def _row(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
        ).fetchone()
        if row is None:
            raise MemoryProtectionMigrationError("memory row disappeared during migration")
        return row
