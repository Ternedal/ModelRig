from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .memory_protected_lookup import (
    LOOKUP_COLUMN,
    LOOKUP_INDEX,
    LOOKUP_MIGRATION_ID,
    LOOKUP_REVISION,
    LOOKUP_SCHEMA,
    LOOKUP_STATE_TABLE,
    ProtectedMemoryExactLookup,
    ProtectedMemoryLookupError,
    new_wrapped_lookup_key,
    unwrap_lookup_key,
    validate_lookup_digest,
    validate_lookup_state_row,
)
from .memory_protection import MemoryProtectionCodec, MemoryProtectionError, MemoryProtectionScope
from .memory_protection_migration import MIGRATION_ID, MIGRATION_SCHEMA, PROTECTION_REVISION


class ProtectedMemoryLookupMigrationError(RuntimeError):
    """The offline protected equality-index migration cannot proceed safely."""


@dataclass(frozen=True)
class ProtectedMemoryLookupMigrationSummary:
    schema: str
    migration_id: str
    provider: str
    key_scope: str
    state: str
    indexed_rows: int
    remaining_rows: int

    @property
    def complete(self) -> bool:
        return self.state == "completed" and self.remaining_rows == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "migration_id": self.migration_id,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "state": self.state,
            "indexed_rows": self.indexed_rows,
            "remaining_rows": self.remaining_rows,
            "complete": self.complete,
            "production_activation": False,
        }


class ProtectedMemoryLookupMigrator:
    """Add a keyed exact-match index to an already protected Memory 3 store.

    This is an explicit offline migration. It creates one random 256-bit HMAC key
    per store, protects that key with the configured current-user provider, and
    stores only domain-separated HMAC-SHA256 values in SQLite. Secret, deleted,
    superseded, redacted and non-protected rows never receive an equality digest.
    """

    def __init__(
        self,
        path: str | Path,
        codec: MemoryProtectionCodec,
        *,
        clock: Callable[[], float] = time.time,
        key_factory: Callable[[int], bytes] | None = None,
        busy_timeout_ms: int = 5_000,
    ):
        self.path = Path(path)
        self.codec = codec
        self.clock = clock
        self.key_factory = key_factory
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))
        self._validate_path()

    def migrate(
        self,
        *,
        batch_limit: int | None = None,
        finalize: bool = True,
    ) -> ProtectedMemoryLookupMigrationSummary:
        if batch_limit is not None and (
            isinstance(batch_limit, bool)
            or not isinstance(batch_limit, int)
            or batch_limit < 1
        ):
            raise ProtectedMemoryLookupMigrationError(
                "batch_limit must be a positive integer"
            )
        conn = self._connect()
        lookup: ProtectedMemoryExactLookup | None = None
        try:
            self._configure_offline_connection(conn)
            self._require_completed_protection(conn)
            self._ensure_schema(conn)
            row = self._ensure_state(conn)
            key = unwrap_lookup_key(self.codec, row)
            lookup = ProtectedMemoryExactLookup(key)
            self._clear_ineligible_digests(conn)

            rows = conn.execute(
                f"SELECT id FROM agent_memories WHERE "
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected' "
                f"AND {LOOKUP_COLUMN} IS NULL ORDER BY created_at,id"
            ).fetchall()
            migrated = 0
            for item in rows:
                if batch_limit is not None and migrated >= batch_limit:
                    break
                self._migrate_one(conn, str(item["id"]), lookup)
                migrated += 1

            summary = self._refresh_summary(conn)
            if finalize and summary.remaining_rows == 0:
                self._finalize(conn, lookup)
                summary = self._refresh_summary(conn, mutate=False)
            return summary
        except (
            sqlite3.Error,
            MemoryProtectionError,
            ProtectedMemoryLookupError,
            ProtectedMemoryLookupMigrationError,
        ) as exc:
            if isinstance(exc, ProtectedMemoryLookupMigrationError):
                raise
            raise ProtectedMemoryLookupMigrationError(
                f"protected exact lookup migration failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            if lookup is not None:
                lookup.close()
            conn.close()

    def inspect(self) -> ProtectedMemoryLookupMigrationSummary:
        conn = self._connect()
        lookup: ProtectedMemoryExactLookup | None = None
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._require_completed_protection(conn)
            self._require_schema(conn)
            row = self._state_row(conn)
            validate_lookup_state_row(row, self.codec, require_completed=False)
            lookup = ProtectedMemoryExactLookup(unwrap_lookup_key(self.codec, row))
            if str(row["state"]) == "completed":
                self._validate_indexed_rows(conn, lookup)
            return self._refresh_summary(conn, mutate=False)
        except (
            sqlite3.Error,
            MemoryProtectionError,
            ProtectedMemoryLookupError,
        ) as exc:
            raise ProtectedMemoryLookupMigrationError(
                f"protected exact lookup inspection failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            if lookup is not None:
                lookup.close()
            conn.close()

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise ProtectedMemoryLookupMigrationError(
                "memory database path must not be a symlink"
            )
        if not self.path.is_file() or self.path.stat().st_size <= 0:
            raise ProtectedMemoryLookupMigrationError(
                "memory database must be a non-empty regular file"
            )

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
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise ProtectedMemoryLookupMigrationError(
                "memory database WAL is busy; stop all worker processes"
            )
        mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        if mode != "delete":
            raise ProtectedMemoryLookupMigrationError(
                "memory database could not enter offline DELETE journal mode"
            )
        lock_mode = str(conn.execute("PRAGMA locking_mode=EXCLUSIVE").fetchone()[0]).lower()
        if lock_mode != "exclusive":
            raise ProtectedMemoryLookupMigrationError(
                "memory database could not enter exclusive lookup migration mode"
            )

    def _require_completed_protection(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupMigrationError(
                "base protected-memory migration receipt is missing"
            )
        if (
            row["schema"] != MIGRATION_SCHEMA
            or row["provider"] != self.codec.provider.provider_id
            or row["key_scope"] != self.codec.provider.key_scope
            or row["state"] != "completed"
            or int(row["scrub_completed"]) != 1
        ):
            raise ProtectedMemoryLookupMigrationError(
                "base protected-memory migration is not lookup-eligible"
            )
        columns = {
            str(item["name"])
            for item in conn.execute("PRAGMA table_info(agent_memories)").fetchall()
        }
        required = {
            "id",
            "subject",
            "predicate",
            "value",
            "sensitivity",
            "review_status",
            "lifecycle_status",
            "schema_version",
            "value_protected",
            "protection_state",
            "protection_revision",
        }
        if not required.issubset(columns):
            raise ProtectedMemoryLookupMigrationError(
                "base protected-memory schema is incomplete"
            )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(item["name"])
            for item in conn.execute("PRAGMA table_info(agent_memories)").fetchall()
        }
        conn.execute("BEGIN EXCLUSIVE")
        try:
            if LOOKUP_COLUMN not in columns:
                conn.execute(
                    f"ALTER TABLE agent_memories ADD COLUMN {LOOKUP_COLUMN} TEXT"
                )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {LOOKUP_STATE_TABLE} (
                    id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    key_scope TEXT NOT NULL,
                    key_ciphertext BLOB NOT NULL,
                    key_ciphertext_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    indexed_rows INTEGER NOT NULL DEFAULT 0,
                    remaining_rows INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {LOOKUP_INDEX} ON agent_memories("
                f"subject,predicate,{LOOKUP_COLUMN},lifecycle_status,review_status,sensitivity)"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        self._require_schema(conn)

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(item["name"])
            for item in conn.execute("PRAGMA table_info(agent_memories)").fetchall()
        }
        if LOOKUP_COLUMN not in columns:
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup column is missing"
            )
        state_columns = {
            str(item["name"])
            for item in conn.execute(f"PRAGMA table_info({LOOKUP_STATE_TABLE})").fetchall()
        }
        expected = {
            "id",
            "schema",
            "provider",
            "key_scope",
            "key_ciphertext",
            "key_ciphertext_sha256",
            "state",
            "revision",
            "started_at",
            "updated_at",
            "completed_at",
            "indexed_rows",
            "remaining_rows",
        }
        if state_columns != expected:
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup migration table schema mismatch"
            )
        index = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            (LOOKUP_INDEX,),
        ).fetchone()
        if index is None or not isinstance(index["sql"], str):
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup index is missing"
            )

    def _ensure_state(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {LOOKUP_STATE_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            kwargs = {} if self.key_factory is None else {"key_factory": self.key_factory}
            key, ciphertext, ciphertext_sha256 = new_wrapped_lookup_key(
                self.codec,
                **kwargs,
            )
            try:
                now = self.clock()
                conn.execute("BEGIN EXCLUSIVE")
                try:
                    conn.execute(
                        f"INSERT INTO {LOOKUP_STATE_TABLE}("
                        "id,schema,provider,key_scope,key_ciphertext,"
                        "key_ciphertext_sha256,state,revision,started_at,updated_at,"
                        "indexed_rows,remaining_rows) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            LOOKUP_MIGRATION_ID,
                            LOOKUP_SCHEMA,
                            self.codec.provider.provider_id,
                            self.codec.provider.key_scope,
                            ciphertext,
                            ciphertext_sha256,
                            "running",
                            LOOKUP_REVISION,
                            now,
                            now,
                            0,
                            0,
                        ),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            finally:
                ProtectedMemoryExactLookup(key).close()
            row = self._state_row(conn)
        validate_lookup_state_row(row, self.codec, require_completed=False)
        return row

    def _state_row(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {LOOKUP_STATE_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup migration receipt is missing"
            )
        return row

    def _clear_ineligible_digests(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            conn.execute(
                f"UPDATE agent_memories SET {LOOKUP_COLUMN}=NULL WHERE "
                f"{LOOKUP_COLUMN} IS NOT NULL AND NOT ("
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected')"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _migrate_one(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        lookup: ProtectedMemoryExactLookup,
    ) -> None:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            row = self._row(conn, memory_id)
            if not self._eligible(row):
                raise ProtectedMemoryLookupMigrationError(
                    "lookup candidate changed eligibility during migration"
                )
            if int(row["protection_revision"]) != PROTECTION_REVISION:
                raise ProtectedMemoryLookupMigrationError(
                    "lookup candidate protection revision mismatch"
                )
            envelope = row["value_protected"]
            if not isinstance(envelope, str) or not envelope:
                raise ProtectedMemoryLookupMigrationError(
                    "lookup candidate value envelope is missing"
                )
            value = self.codec.unprotect_text(
                envelope,
                scope=self._scope(row),
            )
            digest = lookup.digest(
                subject=str(row["subject"]),
                predicate=str(row["predicate"]),
                value=value,
            )
            del value
            conn.execute(
                f"UPDATE agent_memories SET {LOOKUP_COLUMN}=? WHERE id=?",
                (digest, memory_id),
            )
            now = self.clock()
            conn.execute(
                f"UPDATE {LOOKUP_STATE_TABLE} SET state='running',updated_at=?,"
                "completed_at=NULL WHERE id=?",
                (now, LOOKUP_MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _refresh_summary(
        self,
        conn: sqlite3.Connection,
        *,
        mutate: bool = True,
    ) -> ProtectedMemoryLookupMigrationSummary:
        indexed = int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories WHERE "
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected' "
                f"AND {LOOKUP_COLUMN} IS NOT NULL"
            ).fetchone()[0]
        )
        remaining = int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories WHERE "
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected' "
                f"AND {LOOKUP_COLUMN} IS NULL"
            ).fetchone()[0]
        )
        if mutate:
            now = self.clock()
            conn.execute("BEGIN EXCLUSIVE")
            try:
                conn.execute(
                    f"UPDATE {LOOKUP_STATE_TABLE} SET updated_at=?,indexed_rows=?,"
                    "remaining_rows=? WHERE id=?",
                    (now, indexed, remaining, LOOKUP_MIGRATION_ID),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        row = self._state_row(conn)
        validate_lookup_state_row(row, self.codec, require_completed=False)
        return ProtectedMemoryLookupMigrationSummary(
            schema=LOOKUP_SCHEMA,
            migration_id=LOOKUP_MIGRATION_ID,
            provider=str(row["provider"]),
            key_scope=str(row["key_scope"]),
            state=str(row["state"]),
            indexed_rows=indexed,
            remaining_rows=remaining,
        )

    def _finalize(
        self,
        conn: sqlite3.Connection,
        lookup: ProtectedMemoryExactLookup,
    ) -> None:
        self._validate_indexed_rows(conn, lookup)
        remaining = int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories WHERE "
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected' "
                f"AND {LOOKUP_COLUMN} IS NULL"
            ).fetchone()[0]
        )
        if remaining:
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup rows remain before completion"
            )
        completed = self.clock()
        indexed = int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories WHERE "
                "sensitivity='private' AND lifecycle_status='active' "
                "AND protection_state='protected' "
                f"AND {LOOKUP_COLUMN} IS NOT NULL"
            ).fetchone()[0]
        )
        conn.execute("BEGIN EXCLUSIVE")
        try:
            conn.execute(
                f"UPDATE {LOOKUP_STATE_TABLE} SET state='completed',updated_at=?,"
                "completed_at=?,indexed_rows=?,remaining_rows=0 WHERE id=?",
                (completed, completed, indexed, LOOKUP_MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise ProtectedMemoryLookupMigrationError(
                "memory database could not restore WAL journal mode"
            )
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise ProtectedMemoryLookupMigrationError(
                "memory database WAL could not be truncated after lookup migration"
            )
        row = self._state_row(conn)
        validate_lookup_state_row(row, self.codec, require_completed=True)

    def _validate_indexed_rows(
        self,
        conn: sqlite3.Connection,
        lookup: ProtectedMemoryExactLookup,
    ) -> None:
        rows = conn.execute(
            f"SELECT * FROM agent_memories WHERE {LOOKUP_COLUMN} IS NOT NULL ORDER BY id"
        ).fetchall()
        for row in rows:
            if not self._eligible(row):
                raise ProtectedMemoryLookupMigrationError(
                    "ineligible memory row retains a protected lookup digest"
                )
            stored = validate_lookup_digest(row[LOOKUP_COLUMN])
            envelope = row["value_protected"]
            if not isinstance(envelope, str) or not envelope:
                raise ProtectedMemoryLookupMigrationError(
                    "indexed memory value envelope is missing"
                )
            value = self.codec.unprotect_text(envelope, scope=self._scope(row))
            expected = lookup.digest(
                subject=str(row["subject"]),
                predicate=str(row["predicate"]),
                value=value,
            )
            del value
            if stored != expected:
                raise ProtectedMemoryLookupMigrationError(
                    "protected lookup digest does not match encrypted value"
                )
        bad = int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories WHERE {LOOKUP_COLUMN} IS NOT NULL "
                "AND (sensitivity!='private' OR lifecycle_status!='active' "
                "OR protection_state!='protected')"
            ).fetchone()[0]
        )
        if bad:
            raise ProtectedMemoryLookupMigrationError(
                "protected lookup digest exists outside eligible rows"
            )

    @staticmethod
    def _eligible(row: sqlite3.Row) -> bool:
        return (
            row["sensitivity"] == "private"
            and row["lifecycle_status"] == "active"
            and row["protection_state"] == "protected"
        )

    @staticmethod
    def _scope(row: sqlite3.Row) -> MemoryProtectionScope:
        return MemoryProtectionScope(
            memory_id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            sensitivity=str(row["sensitivity"]),
            field="value",
            row_schema_version=int(row["schema_version"]),
        )

    @staticmethod
    def _row(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupMigrationError(
                "memory row disappeared during lookup migration"
            )
        return row
