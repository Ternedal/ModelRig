from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..memory.extraction import VERBATIM_USER_PREDICATE, VERBATIM_USER_SUBJECT
from .memory_protection import (
    ENVELOPE_SCHEMA,
    MemoryProtectionCodec,
    MemoryProtectionError,
    MemoryProtectionScope,
)
from .memory_protection_migration import MIGRATION_ID, MIGRATION_SCHEMA


LOOKUP_SCHEMA = "kaliv-agent3-memory-protected-verbatim-lookup/v1"
LOOKUP_MIGRATION_ID = "agent3-memory-protected-verbatim-lookup-v1"
LOOKUP_MIGRATION_STATES = frozenset({"running", "completed"})
LOOKUP_KEY_BYTES = 32
LOOKUP_DIGEST_HEX_CHARS = 64
MAX_LOOKUP_BATCH = 10_000

_MIGRATION_TABLE = "agent_memory_protected_lookup_migrations"
_INDEX_TABLE = "agent_memory_protected_verbatim_lookup"


class ProtectedMemoryLookupError(RuntimeError):
    """Protected exact-match lookup cannot prove a safe bounded result."""


@dataclass(frozen=True)
class ProtectedMemoryLookupMigrationSummary:
    schema: str
    migration_id: str
    provider: str
    key_scope: str
    state: str
    indexed_total: int
    rows_remaining: int
    batch_commits: int

    @property
    def complete(self) -> bool:
        return self.state == "completed" and self.rows_remaining == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "migration_id": self.migration_id,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "state": self.state,
            "indexed_total": self.indexed_total,
            "rows_remaining": self.rows_remaining,
            "batch_commits": self.batch_commits,
            "complete": self.complete,
            "production_activation": False,
        }


class ProtectedMemoryVerbatimLookup:
    """Keyed blind-index selector for active canonical protected verbatim rows.

    The sidecar is deliberately not an authority source. Its random HMAC key is
    protected by the existing local memory-protection provider. Runtime users may
    use a digest only to select candidate rows, then must decrypt those rows and
    rerun W02-A before mutating durable memory.

    The sidecar is lifecycle-minimal: it must contain exactly the active/private/
    pending-or-confirmed canonical verbatim set. Missing rows *and* stale extra
    rows fail closed. This prevents a delete/supersede from leaving a durable
    content-derived fingerprint behind indefinitely.
    """

    def __init__(self, codec: MemoryProtectionCodec, key: bytes):
        if not isinstance(key, bytes) or len(key) != LOOKUP_KEY_BYTES:
            raise ProtectedMemoryLookupError("protected lookup key has invalid size")
        self.codec = codec
        self._key = bytearray(key)
        self._closed = False

    @classmethod
    def load_locked(
        cls,
        conn: sqlite3.Connection,
        codec: MemoryProtectionCodec,
    ) -> "ProtectedMemoryVerbatimLookup":
        _require_schema(conn)
        row = conn.execute(
            f"SELECT * FROM {_MIGRATION_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupError(
                "protected verbatim lookup migration receipt is missing"
            )
        _validate_receipt(row, codec, require_completed=True)
        return cls(codec, _open_lookup_key(row, codec))

    def close(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0
        self._closed = True

    def __enter__(self) -> "ProtectedMemoryVerbatimLookup":
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def fingerprint(self, value: str) -> str:
        self._require_open()
        if not isinstance(value, str) or not value or value != value.strip():
            raise ProtectedMemoryLookupError(
                "protected lookup value must be canonical non-empty text"
            )
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProtectedMemoryLookupError(
                "protected lookup value is not valid UTF-8"
            ) from exc
        message = _canonical_json(
            {
                "namespace": "agent3-memory-protected-verbatim-lookup",
                "schema": LOOKUP_SCHEMA,
                "subject": VERBATIM_USER_SUBJECT,
                "predicate": VERBATIM_USER_PREDICATE,
                "value": encoded.decode("utf-8"),
            }
        )
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def assert_complete_for_active_locked(self, conn: sqlite3.Connection) -> None:
        """Fail closed unless sidecar == the complete eligible active set."""
        self._require_open()
        _require_schema(conn)
        eligible = _eligible_count(conn)
        total_indexed = int(conn.execute(f"SELECT COUNT(*) FROM {_INDEX_TABLE}").fetchone()[0])
        joined = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {_INDEX_TABLE} i "
                "JOIN agent_memories m ON m.id=i.memory_id "
                "WHERE i.schema=? AND " + _ELIGIBLE_SQL.replace("subject", "m.subject")
                .replace("predicate", "m.predicate")
                .replace("sensitivity", "m.sensitivity")
                .replace("protection_state", "m.protection_state")
                .replace("lifecycle_status", "m.lifecycle_status")
                .replace("review_status", "m.review_status"),
                (LOOKUP_SCHEMA,),
            ).fetchone()[0]
        )
        invalid = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {_INDEX_TABLE} WHERE schema<>? "
                "OR length(value_hmac)<>? OR value_hmac GLOB '*[^0-9a-f]*'",
                (LOOKUP_SCHEMA, LOOKUP_DIGEST_HEX_CHARS),
            ).fetchone()[0]
        )
        if eligible != joined or total_indexed != eligible or invalid != 0:
            raise ProtectedMemoryLookupError(
                "protected verbatim lookup is stale or incomplete for active durable state"
            )

    def index_created_locked(
        self,
        conn: sqlite3.Connection,
        *,
        memory_id: str,
        subject: str,
        predicate: str,
        value: str,
        sensitivity: str,
        review_status: str,
        lifecycle_status: str = "active",
        indexed_at: float,
    ) -> None:
        """Index one just-created eligible row in the caller's write transaction."""
        self._require_open()
        if not _eligible_fields(
            subject=subject,
            predicate=predicate,
            sensitivity=sensitivity,
            review_status=review_status,
            lifecycle_status=lifecycle_status,
        ):
            return
        digest = self.fingerprint(value)
        try:
            conn.execute(
                f"INSERT INTO {_INDEX_TABLE}(memory_id,schema,value_hmac,indexed_at) "
                "VALUES(?,?,?,?)",
                (memory_id, LOOKUP_SCHEMA, digest, float(indexed_at)),
            )
        except sqlite3.IntegrityError as exc:
            raise ProtectedMemoryLookupError(
                "protected verbatim lookup already contains the memory id"
            ) from exc

    def remove_locked(self, conn: sqlite3.Connection, *, memory_id: str) -> None:
        """Remove a row that became non-active inside the same write transaction."""
        self._require_open()
        changed = conn.execute(
            f"DELETE FROM {_INDEX_TABLE} WHERE memory_id=?",
            (memory_id,),
        ).rowcount
        if changed != 1:
            raise ProtectedMemoryLookupError(
                "protected verbatim predecessor is missing from the blind index"
            )

    def _require_open(self) -> None:
        if self._closed:
            raise ProtectedMemoryLookupError("protected verbatim lookup is closed")


class ProtectedMemoryVerbatimLookupMigrator:
    """Explicit resumable offline migration for the keyed verbatim blind index.

    Migration is local-only and never activates chat/Agent 3. It requires the base
    protected-memory migration to be complete, then repairs the sidecar toward the
    exact active eligible set. Both stale-row pruning and missing-row indexing are
    resumable under ``batch_limit``. The random lookup key is generated once and
    stored only as provider-protected ciphertext.
    """

    def __init__(
        self,
        path: str | Path,
        codec: MemoryProtectionCodec,
        *,
        clock: Callable[[], float] = time.time,
        key_factory: Callable[[int], bytes] = os.urandom,
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
    ) -> ProtectedMemoryLookupMigrationSummary:
        limit = self._batch_limit(batch_limit)
        conn = self._connect()
        try:
            self._configure_offline_connection(conn)
            self._require_base_migration(conn)
            self._ensure_schema(conn)
            receipt = self._ensure_receipt(conn)
            key = bytearray(_open_lookup_key(receipt, self.codec))
            try:
                stale_before = self._stale_count(conn)
                missing_before = self._missing_count(conn)
                if (stale_before or missing_before) and receipt["state"] == "completed":
                    self._set_running(conn)

                remaining_budget = limit
                stale_ids = self._stale_ids(conn, remaining_budget)
                for memory_id in stale_ids:
                    self._delete_one(conn, memory_id)
                    remaining_budget -= 1

                if remaining_budget:
                    missing_ids = self._missing_ids(conn, remaining_budget)
                    for memory_id in missing_ids:
                        self._index_one(conn, memory_id, key)
                        remaining_budget -= 1

                return self._refresh_summary(conn)
            finally:
                for index in range(len(key)):
                    key[index] = 0
        except (sqlite3.Error, MemoryProtectionError) as exc:
            if isinstance(exc, ProtectedMemoryLookupError):
                raise
            raise ProtectedMemoryLookupError(
                f"protected verbatim lookup migration failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            conn.close()

    def inspect(self) -> ProtectedMemoryLookupMigrationSummary:
        conn = self._connect()
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._require_base_migration(conn)
            _require_schema(conn)
            row = conn.execute(
                f"SELECT * FROM {_MIGRATION_TABLE} WHERE id=?",
                (LOOKUP_MIGRATION_ID,),
            ).fetchone()
            if row is None:
                raise ProtectedMemoryLookupError(
                    "protected verbatim lookup migration receipt is missing"
                )
            _validate_receipt(row, self.codec, require_completed=False)
            key = bytearray(_open_lookup_key(row, self.codec))
            for index in range(len(key)):
                key[index] = 0
            return self._summary(conn, row)
        finally:
            conn.close()

    @staticmethod
    def _batch_limit(value: int | None) -> int:
        if value is None:
            return MAX_LOOKUP_BATCH
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProtectedMemoryLookupError("batch_limit must be an integer")
        if value < 1 or value > MAX_LOOKUP_BATCH:
            raise ProtectedMemoryLookupError(
                f"batch_limit must be 1..{MAX_LOOKUP_BATCH}"
            )
        return value

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise ProtectedMemoryLookupError("memory database path must not be a symlink")
        if not self.path.is_file() or self.path.stat().st_size <= 0:
            raise ProtectedMemoryLookupError(
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
        try:
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.OperationalError as exc:
            raise ProtectedMemoryLookupError(
                "lookup migration requires all worker processes to be stopped"
            ) from exc
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise ProtectedMemoryLookupError(
                "lookup migration cannot acquire an offline WAL checkpoint"
            )
        mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        if mode != "delete":
            raise ProtectedMemoryLookupError(
                "lookup migration could not enter offline DELETE journal mode"
            )
        lock_mode = str(conn.execute("PRAGMA locking_mode=EXCLUSIVE").fetchone()[0]).lower()
        if lock_mode != "exclusive":
            raise ProtectedMemoryLookupError(
                "lookup migration could not enter exclusive locking mode"
            )

    def _require_base_migration(self, conn: sqlite3.Connection) -> None:
        try:
            row = conn.execute(
                "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
                (MIGRATION_ID,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ProtectedMemoryLookupError(
                "base protected-memory migration is missing"
            ) from exc
        if row is None:
            raise ProtectedMemoryLookupError(
                "base protected-memory migration receipt is missing"
            )
        if (
            row["schema"] != MIGRATION_SCHEMA
            or row["provider"] != self.codec.provider.provider_id
            or row["key_scope"] != self.codec.provider.key_scope
            or row["state"] != "completed"
            or int(row["scrub_completed"]) != 1
        ):
            raise ProtectedMemoryLookupError(
                "base protected-memory migration is not lookup-eligible"
            )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} (
                    id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    key_scope TEXT NOT NULL,
                    state TEXT NOT NULL,
                    key_ciphertext_b64 TEXT NOT NULL,
                    key_ciphertext_sha256 TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    indexed_rows INTEGER NOT NULL DEFAULT 0,
                    batch_commits INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_INDEX_TABLE} (
                    memory_id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL,
                    value_hmac TEXT NOT NULL,
                    indexed_at REAL NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES agent_memories(id)
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_agent_memory_protected_verbatim_hmac "
                f"ON {_INDEX_TABLE}(value_hmac,memory_id)"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _require_schema(conn)

    def _ensure_receipt(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {_MIGRATION_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            key = self.key_factory(LOOKUP_KEY_BYTES)
            if not isinstance(key, bytes) or len(key) != LOOKUP_KEY_BYTES:
                raise ProtectedMemoryLookupError(
                    "lookup key factory must return exactly 32 bytes"
                )
            ciphertext = self.codec.provider.protect(
                key,
                entropy=_lookup_key_entropy(self.codec),
            )
            if not isinstance(ciphertext, bytes) or not ciphertext:
                raise ProtectedMemoryLookupError(
                    "protection provider returned no lookup-key ciphertext"
                )
            now = self.clock()
            conn.execute("BEGIN EXCLUSIVE")
            try:
                conn.execute(
                    f"INSERT INTO {_MIGRATION_TABLE}("
                    "id,schema,provider,key_scope,state,key_ciphertext_b64,"
                    "key_ciphertext_sha256,started_at,updated_at,completed_at,"
                    "indexed_rows,batch_commits) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        LOOKUP_MIGRATION_ID,
                        LOOKUP_SCHEMA,
                        self.codec.provider.provider_id,
                        self.codec.provider.key_scope,
                        "running",
                        base64.b64encode(ciphertext).decode("ascii"),
                        hashlib.sha256(ciphertext).hexdigest(),
                        now,
                        now,
                        None,
                        0,
                        0,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            row = conn.execute(
                f"SELECT * FROM {_MIGRATION_TABLE} WHERE id=?",
                (LOOKUP_MIGRATION_ID,),
            ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupError(
                "protected verbatim lookup receipt could not be created"
            )
        _validate_receipt(row, self.codec, require_completed=False)
        return row

    def _stale_ids(self, conn: sqlite3.Connection, limit: int) -> list[str]:
        if limit <= 0:
            return []
        rows = conn.execute(
            f"SELECT i.memory_id FROM {_INDEX_TABLE} i "
            "LEFT JOIN agent_memories m ON m.id=i.memory_id AND "
            + _ELIGIBLE_SQL.replace("subject", "m.subject")
            .replace("predicate", "m.predicate")
            .replace("sensitivity", "m.sensitivity")
            .replace("protection_state", "m.protection_state")
            .replace("lifecycle_status", "m.lifecycle_status")
            .replace("review_status", "m.review_status")
            + " WHERE m.id IS NULL OR i.schema<>? ORDER BY i.memory_id LIMIT ?",
            (LOOKUP_SCHEMA, limit),
        ).fetchall()
        return [str(row["memory_id"]) for row in rows]

    def _missing_ids(self, conn: sqlite3.Connection, limit: int) -> list[str]:
        if limit <= 0:
            return []
        rows = conn.execute(
            f"SELECT m.id FROM agent_memories m LEFT JOIN {_INDEX_TABLE} i "
            "ON i.memory_id=m.id WHERE "
            + _ELIGIBLE_SQL.replace("subject", "m.subject")
            .replace("predicate", "m.predicate")
            .replace("sensitivity", "m.sensitivity")
            .replace("protection_state", "m.protection_state")
            .replace("lifecycle_status", "m.lifecycle_status")
            .replace("review_status", "m.review_status")
            + " AND i.memory_id IS NULL ORDER BY m.created_at,m.id LIMIT ?",
            (limit,),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _stale_count(self, conn: sqlite3.Connection) -> int:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {_INDEX_TABLE} i "
                "LEFT JOIN agent_memories m ON m.id=i.memory_id AND "
                + _ELIGIBLE_SQL.replace("subject", "m.subject")
                .replace("predicate", "m.predicate")
                .replace("sensitivity", "m.sensitivity")
                .replace("protection_state", "m.protection_state")
                .replace("lifecycle_status", "m.lifecycle_status")
                .replace("review_status", "m.review_status")
                + " WHERE m.id IS NULL OR i.schema<>?",
                (LOOKUP_SCHEMA,),
            ).fetchone()[0]
        )

    def _missing_count(self, conn: sqlite3.Connection) -> int:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM agent_memories m LEFT JOIN {_INDEX_TABLE} i "
                "ON i.memory_id=m.id WHERE "
                + _ELIGIBLE_SQL.replace("subject", "m.subject")
                .replace("predicate", "m.predicate")
                .replace("sensitivity", "m.sensitivity")
                .replace("protection_state", "m.protection_state")
                .replace("lifecycle_status", "m.lifecycle_status")
                .replace("review_status", "m.review_status")
                + " AND i.memory_id IS NULL"
            ).fetchone()[0]
        )

    def _set_running(self, conn: sqlite3.Connection) -> None:
        now = self.clock()
        conn.execute("BEGIN EXCLUSIVE")
        try:
            changed = conn.execute(
                f"UPDATE {_MIGRATION_TABLE} SET state='running',updated_at=?,"
                "completed_at=NULL WHERE id=?",
                (now, LOOKUP_MIGRATION_ID),
            ).rowcount
            if changed != 1:
                raise ProtectedMemoryLookupError("lookup migration receipt disappeared")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _delete_one(self, conn: sqlite3.Connection, memory_id: str) -> None:
        now = self.clock()
        conn.execute("BEGIN EXCLUSIVE")
        try:
            changed = conn.execute(
                f"DELETE FROM {_INDEX_TABLE} WHERE memory_id=?",
                (memory_id,),
            ).rowcount
            if changed != 1:
                raise ProtectedMemoryLookupError(
                    "stale lookup row disappeared during offline repair"
                )
            conn.execute(
                f"UPDATE {_MIGRATION_TABLE} SET indexed_rows=(SELECT COUNT(*) FROM {_INDEX_TABLE}),"
                "batch_commits=batch_commits+1,updated_at=? WHERE id=?",
                (now, LOOKUP_MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _index_one(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        key: bytearray,
    ) -> None:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            row = conn.execute(
                "SELECT * FROM agent_memories WHERE id=?",
                (memory_id,),
            ).fetchone()
            if row is None or not _row_eligible(row):
                raise ProtectedMemoryLookupError(
                    "lookup migration lost an eligible selected memory row"
                )
            existing = conn.execute(
                f"SELECT memory_id FROM {_INDEX_TABLE} WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return
            value = _open_row_value(row, self.codec)
            digest = _fingerprint(bytes(key), value)
            now = self.clock()
            conn.execute(
                f"INSERT INTO {_INDEX_TABLE}(memory_id,schema,value_hmac,indexed_at) "
                "VALUES(?,?,?,?)",
                (memory_id, LOOKUP_SCHEMA, digest, now),
            )
            conn.execute(
                f"UPDATE {_MIGRATION_TABLE} SET indexed_rows=(SELECT COUNT(*) FROM {_INDEX_TABLE}),"
                "batch_commits=batch_commits+1,updated_at=? WHERE id=?",
                (now, LOOKUP_MIGRATION_ID),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _refresh_summary(
        self, conn: sqlite3.Connection
    ) -> ProtectedMemoryLookupMigrationSummary:
        remaining = self._stale_count(conn) + self._missing_count(conn)
        if remaining == 0:
            now = self.clock()
            conn.execute("BEGIN EXCLUSIVE")
            try:
                changed = conn.execute(
                    f"UPDATE {_MIGRATION_TABLE} SET state='completed',updated_at=?,"
                    "completed_at=COALESCE(completed_at,?),"
                    f"indexed_rows=(SELECT COUNT(*) FROM {_INDEX_TABLE}) WHERE id=?",
                    (now, now, LOOKUP_MIGRATION_ID),
                ).rowcount
                if changed != 1:
                    raise ProtectedMemoryLookupError("lookup migration receipt disappeared")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        row = conn.execute(
            f"SELECT * FROM {_MIGRATION_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupError("lookup migration receipt disappeared")
        return self._summary(conn, row)

    def _summary(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> ProtectedMemoryLookupMigrationSummary:
        _validate_receipt(row, self.codec, require_completed=False)
        indexed_total = int(conn.execute(f"SELECT COUNT(*) FROM {_INDEX_TABLE}").fetchone()[0])
        remaining = self._stale_count(conn) + self._missing_count(conn)
        if row["state"] == "completed" and remaining != 0:
            raise ProtectedMemoryLookupError(
                "completed lookup receipt does not match durable state"
            )
        return ProtectedMemoryLookupMigrationSummary(
            schema=LOOKUP_SCHEMA,
            migration_id=LOOKUP_MIGRATION_ID,
            provider=self.codec.provider.provider_id,
            key_scope=self.codec.provider.key_scope,
            state=str(row["state"]),
            indexed_total=indexed_total,
            rows_remaining=remaining,
            batch_commits=int(row["batch_commits"]),
        )


def _require_schema(conn: sqlite3.Connection) -> None:
    migration = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_MIGRATION_TABLE})")
    }
    expected_migration = {
        "id",
        "schema",
        "provider",
        "key_scope",
        "state",
        "key_ciphertext_b64",
        "key_ciphertext_sha256",
        "started_at",
        "updated_at",
        "completed_at",
        "indexed_rows",
        "batch_commits",
    }
    index = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({_INDEX_TABLE})")}
    expected_index = {"memory_id", "schema", "value_hmac", "indexed_at"}
    if migration != expected_migration or index != expected_index:
        raise ProtectedMemoryLookupError(
            "protected verbatim lookup schema is missing or incompatible"
        )


def _validate_receipt(
    row: sqlite3.Row,
    codec: MemoryProtectionCodec,
    *,
    require_completed: bool,
) -> None:
    if row["schema"] != LOOKUP_SCHEMA:
        raise ProtectedMemoryLookupError("protected lookup schema mismatch")
    if row["provider"] != codec.provider.provider_id:
        raise ProtectedMemoryLookupError("protected lookup provider mismatch")
    if row["key_scope"] != codec.provider.key_scope:
        raise ProtectedMemoryLookupError("protected lookup key scope mismatch")
    if row["state"] not in LOOKUP_MIGRATION_STATES:
        raise ProtectedMemoryLookupError("protected lookup migration state is invalid")
    if require_completed and row["state"] != "completed":
        raise ProtectedMemoryLookupError(
            "protected verbatim lookup migration is incomplete"
        )
    digest = row["key_ciphertext_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != LOOKUP_DIGEST_HEX_CHARS
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ProtectedMemoryLookupError(
            "protected lookup key ciphertext digest is invalid"
        )


def _open_lookup_key(row: sqlite3.Row, codec: MemoryProtectionCodec) -> bytes:
    payload = row["key_ciphertext_b64"]
    if not isinstance(payload, str) or not payload:
        raise ProtectedMemoryLookupError("protected lookup key ciphertext is missing")
    try:
        ciphertext = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProtectedMemoryLookupError(
            "protected lookup key ciphertext is not valid base64"
        ) from exc
    if hashlib.sha256(ciphertext).hexdigest() != row["key_ciphertext_sha256"]:
        raise ProtectedMemoryLookupError(
            "protected lookup key ciphertext digest mismatch"
        )
    try:
        key = codec.provider.unprotect(
            ciphertext,
            entropy=_lookup_key_entropy(codec),
        )
    except MemoryProtectionError:
        raise
    except Exception as exc:
        raise ProtectedMemoryLookupError(
            "protection provider could not open the lookup key"
        ) from exc
    if not isinstance(key, bytes) or len(key) != LOOKUP_KEY_BYTES:
        raise ProtectedMemoryLookupError("unprotected lookup key has invalid size")
    return key


def _lookup_key_entropy(codec: MemoryProtectionCodec) -> bytes:
    return hashlib.sha256(
        _canonical_json(
            {
                "namespace": "agent3-memory-protected-verbatim-lookup-key",
                "schema": LOOKUP_SCHEMA,
                "provider": codec.provider.provider_id,
                "key_scope": codec.provider.key_scope,
            }
        )
    ).digest()


def _eligible_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM agent_memories WHERE " + _ELIGIBLE_SQL).fetchone()[0]
    )


def _eligible_fields(
    *,
    subject: str,
    predicate: str,
    sensitivity: str,
    review_status: str,
    lifecycle_status: str,
) -> bool:
    return (
        subject == VERBATIM_USER_SUBJECT
        and predicate == VERBATIM_USER_PREDICATE
        and sensitivity == "private"
        and review_status in {"pending", "confirmed"}
        and lifecycle_status == "active"
    )


def _row_eligible(row: sqlite3.Row) -> bool:
    return _eligible_fields(
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        sensitivity=str(row["sensitivity"]),
        review_status=str(row["review_status"]),
        lifecycle_status=str(row["lifecycle_status"]),
    ) and row["protection_state"] == "protected"


def _open_row_value(row: sqlite3.Row, codec: MemoryProtectionCodec) -> str:
    if (
        not _row_eligible(row)
        or row["value"] != ""
        or row["source_ref"] is not None
        or not isinstance(row["value_protected"], str)
        or not row["value_protected"]
        or row["protection_schema"] != ENVELOPE_SCHEMA
        or row["protection_provider"] != codec.provider.provider_id
        or row["protection_key_scope"] != codec.provider.key_scope
    ):
        raise ProtectedMemoryLookupError(
            "canonical lookup row violates protected-memory invariants"
        )
    return codec.unprotect_text(
        str(row["value_protected"]),
        scope=MemoryProtectionScope(
            memory_id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            sensitivity=str(row["sensitivity"]),
            field="value",
            row_schema_version=int(row["schema_version"]),
        ),
    )


def _fingerprint(key: bytes, value: str) -> str:
    message = _canonical_json(
        {
            "namespace": "agent3-memory-protected-verbatim-lookup",
            "schema": LOOKUP_SCHEMA,
            "subject": VERBATIM_USER_SUBJECT,
            "predicate": VERBATIM_USER_PREDICATE,
            "value": value,
        }
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _canonical_json(value: dict[str, str]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


_ELIGIBLE_SQL = (
    "subject='" + VERBATIM_USER_SUBJECT + "' AND "
    "predicate='" + VERBATIM_USER_PREDICATE + "' AND "
    "sensitivity='private' AND protection_state='protected' AND "
    "lifecycle_status='active' AND review_status IN ('pending','confirmed')"
)
