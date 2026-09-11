from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..memory.extraction import VERBATIM_USER_PREDICATE, VERBATIM_USER_SUBJECT
from .memory import MemoryStoreError
from .memory_protected_reader import ProtectedMemoryReader
from .memory_protection import (
    MemoryProtectionCodec,
    MemoryProtectionError,
    MemoryProtectionScope,
)


EXACT_LOOKUP_SCHEMA = "kaliv-agent3-memory-protected-exact-lookup/v1"
EXACT_LOOKUP_ID = "protected-verbatim-exact-match-v1"
EXACT_LOOKUP_REVISION = 1
MAX_EXACT_LOOKUP_MATCHES = 129

_META_TABLE = "agent_memory_protected_exact_lookup_meta"
_INDEX_TABLE = "agent_memory_protected_exact_lookup"
_KEY_SCOPE = MemoryProtectionScope(
    memory_id="memory-protected-exact-lookup-key-v1",
    subject="system",
    predicate="protected_verbatim_exact_lookup_key",
    sensitivity="private",
    field="value",
    row_schema_version=1,
)
_KEY_BYTES = 32
_DIGEST_BYTES = hashlib.sha256().digest_size


class ProtectedMemoryExactLookupError(MemoryStoreError):
    """The protected exact-match sidecar cannot prove a bounded safe lookup."""


@dataclass(frozen=True)
class ProtectedMemoryExactLookupSummary:
    schema: str
    lookup_id: str
    provider: str
    key_scope: str
    state: str
    indexed_rows: int
    revision: int

    @property
    def complete(self) -> bool:
        return self.state == "completed" and self.revision == EXACT_LOOKUP_REVISION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lookup_id": self.lookup_id,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "state": self.state,
            "indexed_rows": self.indexed_rows,
            "revision": self.revision,
            "complete": self.complete,
            "production_activation": False,
        }


class ProtectedMemoryExactLookupMigrator:
    """Explicitly build/rebuild a keyed exact-match sidecar for protected verbatim rows.

    The sidecar stores only HMAC-SHA256 digests. Its random HMAC key is itself
    protected by the existing local protection provider and never written to a
    plaintext SQLite column. Migration is explicit, local and atomic; this class
    is not imported by startup or any HTTP/chat path.
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

    def migrate(self) -> ProtectedMemoryExactLookupSummary:
        # Reuse the existing reader boundary first. It proves the base protection
        # migration is complete, the provider/key scope matches and protected
        # rows retain no plaintext before this sidecar is allowed to exist.
        with ProtectedMemoryReader(
            self.path,
            self.codec,
            busy_timeout_ms=self.busy_timeout_ms,
        ):
            pass

        conn = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA secure_delete=ON")
            mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
            if mode != "wal":
                raise ProtectedMemoryExactLookupError(
                    "protected exact lookup migration requires WAL journal mode"
                )
            conn.execute("BEGIN IMMEDIATE")
            try:
                _ensure_schema(conn.execute)
                key = _ensure_migration_key(
                    conn.execute,
                    self.codec,
                    now=self.clock(),
                )
                conn.execute(f"DELETE FROM {_INDEX_TABLE}")
                rows = conn.execute(
                    "SELECT * FROM agent_memories WHERE " + _QUALIFYING_SQL + " "
                    "ORDER BY id"
                ).fetchall()
                now = self.clock()
                for row in rows:
                    value = _open_row_value(row, self.codec)
                    conn.execute(
                        f"INSERT INTO {_INDEX_TABLE}("
                        "memory_id,value_hmac,revision,updated_at) VALUES(?,?,?,?)",
                        (
                            str(row["id"]),
                            _value_digest(key, value),
                            EXACT_LOOKUP_REVISION,
                            now,
                        ),
                    )
                conn.execute(
                    f"UPDATE {_META_TABLE} SET state='completed',indexed_rows=?,"
                    "updated_at=? WHERE id=?",
                    (len(rows), now, EXACT_LOOKUP_ID),
                )
                _validate_complete_index(conn.execute, self.codec)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            return protected_exact_lookup_summary(conn.execute, self.codec)
        except (
            sqlite3.Error,
            MemoryProtectionError,
            ProtectedMemoryExactLookupError,
        ) as exc:
            if isinstance(exc, ProtectedMemoryExactLookupError):
                raise
            raise ProtectedMemoryExactLookupError(
                f"protected exact lookup migration failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            conn.close()

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise ProtectedMemoryExactLookupError(
                "memory database path must not be a symlink"
            )
        if not self.path.is_file() or self.path.stat().st_size <= 0:
            raise ProtectedMemoryExactLookupError(
                "memory database must be a non-empty regular file"
            )


def protected_exact_lookup_summary(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
) -> ProtectedMemoryExactLookupSummary:
    state = _load_state(execute, codec, absent_ok=False, require_completed=False)
    assert state is not None
    row, _key = state
    return ProtectedMemoryExactLookupSummary(
        schema=str(row["schema"]),
        lookup_id=str(row["id"]),
        provider=str(row["provider"]),
        key_scope=str(row["key_scope"]),
        state=str(row["state"]),
        indexed_rows=int(row["indexed_rows"]),
        revision=int(row["revision"]),
    )


def protected_exact_lookup_ids(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    value: str,
    limit: int = MAX_EXACT_LOOKUP_MATCHES,
) -> tuple[str, ...] | None:
    """Return bounded candidate ids, or ``None`` when the sidecar is not installed.

    A digest match is only a selector. Callers must decrypt the selected rows and
    apply their normal exact-value/authority validation before using a match.
    """
    selected_limit = _limit(limit)
    state = _load_state(execute, codec, absent_ok=True, require_completed=True)
    if state is None:
        return None
    _row, key = state
    _validate_complete_index(execute, codec, loaded_state=state)
    digest = _value_digest(key, _clean_value(value))
    rows = execute(
        f"SELECT i.memory_id FROM {_INDEX_TABLE} i "
        "JOIN agent_memories m ON m.id=i.memory_id "
        "WHERE i.value_hmac=? AND i.revision=? AND "
        + _QUALIFYING_SQL.replace("subject", "m.subject")
        .replace("predicate", "m.predicate")
        .replace("sensitivity", "m.sensitivity")
        .replace("review_status", "m.review_status")
        .replace("lifecycle_status", "m.lifecycle_status")
        + " ORDER BY i.memory_id LIMIT ?",
        (digest, EXACT_LOOKUP_REVISION, selected_limit),
    ).fetchall()
    return tuple(str(row["memory_id"]) for row in rows)


def sync_protected_exact_lookup_row(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    memory_id: str,
    subject: str,
    predicate: str,
    value: str,
    sensitivity: str,
    review_status: str,
    lifecycle_status: str,
    now: float,
) -> bool:
    """Maintain one sidecar row inside an already-held protected write transaction.

    Returns ``False`` only when the optional sidecar has never been installed.
    If sidecar tables exist but are incomplete or invalid, the write fails closed.
    """
    state = _load_state(execute, codec, absent_ok=True, require_completed=True)
    if state is None:
        return False
    _meta, key = state
    if _qualifies(
        subject=subject,
        predicate=predicate,
        sensitivity=sensitivity,
        review_status=review_status,
        lifecycle_status=lifecycle_status,
    ):
        execute(
            f"INSERT INTO {_INDEX_TABLE}(memory_id,value_hmac,revision,updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET "
            "value_hmac=excluded.value_hmac,revision=excluded.revision,"
            "updated_at=excluded.updated_at",
            (
                _clean_id(memory_id),
                _value_digest(key, _clean_value(value)),
                EXACT_LOOKUP_REVISION,
                float(now),
            ),
        )
    else:
        execute(
            f"DELETE FROM {_INDEX_TABLE} WHERE memory_id=?",
            (_clean_id(memory_id),),
        )
    _refresh_indexed_count(execute, now=float(now))
    return True


def remove_protected_exact_lookup_row(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    memory_id: str,
    now: float,
) -> bool:
    state = _load_state(execute, codec, absent_ok=True, require_completed=True)
    if state is None:
        return False
    execute(
        f"DELETE FROM {_INDEX_TABLE} WHERE memory_id=?",
        (_clean_id(memory_id),),
    )
    _refresh_indexed_count(execute, now=float(now))
    return True


def _ensure_schema(execute: Callable[..., sqlite3.Cursor]) -> None:
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_META_TABLE} (
            id TEXT PRIMARY KEY,
            schema TEXT NOT NULL,
            provider TEXT NOT NULL,
            key_scope TEXT NOT NULL,
            state TEXT NOT NULL,
            key_protected TEXT NOT NULL,
            indexed_rows INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_INDEX_TABLE} (
            memory_id TEXT PRIMARY KEY REFERENCES agent_memories(id) ON DELETE CASCADE,
            value_hmac TEXT NOT NULL,
            revision INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS idx_agent_memory_protected_exact_lookup_hmac "
        f"ON {_INDEX_TABLE}(value_hmac,memory_id)"
    )
    _require_schema(execute)


def _require_schema(execute: Callable[..., sqlite3.Cursor]) -> None:
    expected_meta = {
        "id",
        "schema",
        "provider",
        "key_scope",
        "state",
        "key_protected",
        "indexed_rows",
        "revision",
        "updated_at",
    }
    expected_index = {"memory_id", "value_hmac", "revision", "updated_at"}
    meta = _table_columns(execute, _META_TABLE)
    index = _table_columns(execute, _INDEX_TABLE)
    if not meta and not index:
        raise ProtectedMemoryExactLookupError("protected exact lookup is not installed")
    if meta != expected_meta or index != expected_index:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup schema is incomplete or unexpected"
        )


def _tables_present(execute: Callable[..., sqlite3.Cursor]) -> bool:
    names = {
        str(row[0])
        for row in execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
            (_META_TABLE, _INDEX_TABLE),
        ).fetchall()
    }
    if not names:
        return False
    if names != {_META_TABLE, _INDEX_TABLE}:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup sidecar is only partially installed"
        )
    return True


def _table_columns(
    execute: Callable[..., sqlite3.Cursor], table: str
) -> set[str]:
    return {str(row[1]) for row in execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_migration_key(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    now: float,
) -> bytes:
    row = execute(
        f"SELECT * FROM {_META_TABLE} WHERE id=?",
        (EXACT_LOOKUP_ID,),
    ).fetchone()
    if row is not None:
        state = _validate_meta(row, codec, require_completed=False)
        return state

    key_hex = secrets.token_hex(_KEY_BYTES)
    try:
        envelope = codec.protect_text(key_hex, scope=_KEY_SCOPE)
    except MemoryProtectionError as exc:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup key could not be protected"
        ) from exc
    execute(
        f"INSERT INTO {_META_TABLE}("
        "id,schema,provider,key_scope,state,key_protected,indexed_rows,revision,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            EXACT_LOOKUP_ID,
            EXACT_LOOKUP_SCHEMA,
            codec.provider.provider_id,
            codec.provider.key_scope,
            "building",
            envelope,
            0,
            EXACT_LOOKUP_REVISION,
            float(now),
        ),
    )
    return bytes.fromhex(key_hex)


def _load_state(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    absent_ok: bool,
    require_completed: bool,
) -> tuple[sqlite3.Row, bytes] | None:
    if not _tables_present(execute):
        if absent_ok:
            return None
        raise ProtectedMemoryExactLookupError("protected exact lookup is not installed")
    _require_schema(execute)
    rows = execute(f"SELECT * FROM {_META_TABLE}").fetchall()
    if len(rows) != 1 or str(rows[0]["id"]) != EXACT_LOOKUP_ID:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup metadata cardinality is invalid"
        )
    row = rows[0]
    key = _validate_meta(row, codec, require_completed=require_completed)
    return row, key


def _validate_meta(
    row: sqlite3.Row,
    codec: MemoryProtectionCodec,
    *,
    require_completed: bool,
) -> bytes:
    state = str(row["state"])
    if (
        row["schema"] != EXACT_LOOKUP_SCHEMA
        or row["provider"] != codec.provider.provider_id
        or row["key_scope"] != codec.provider.key_scope
        or int(row["revision"]) != EXACT_LOOKUP_REVISION
        or state not in {"building", "completed"}
    ):
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup metadata does not match this store/provider"
        )
    if require_completed and state != "completed":
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup migration is not complete"
        )
    envelope = row["key_protected"]
    if not isinstance(envelope, str) or not envelope:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup key envelope is missing"
        )
    try:
        key_hex = codec.unprotect_text(envelope, scope=_KEY_SCOPE)
        key = bytes.fromhex(key_hex)
    except (MemoryProtectionError, ValueError) as exc:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup key could not be opened"
        ) from exc
    if len(key) != _KEY_BYTES:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup key has invalid length"
        )
    return key


def _validate_complete_index(
    execute: Callable[..., sqlite3.Cursor],
    codec: MemoryProtectionCodec,
    *,
    loaded_state: tuple[sqlite3.Row, bytes] | None = None,
) -> None:
    state = loaded_state or _load_state(
        execute,
        codec,
        absent_ok=False,
        require_completed=True,
    )
    assert state is not None
    meta, _key = state
    if str(meta["state"]) != "completed":
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup migration is not complete"
        )
    active_count = int(
        execute(
            "SELECT COUNT(*) FROM agent_memories WHERE " + _QUALIFYING_SQL
        ).fetchone()[0]
    )
    total_indexed = int(execute(f"SELECT COUNT(*) FROM {_INDEX_TABLE}").fetchone()[0])
    joined_count = int(
        execute(
            f"SELECT COUNT(*) FROM {_INDEX_TABLE} i "
            "JOIN agent_memories m ON m.id=i.memory_id WHERE "
            + _QUALIFYING_SQL.replace("subject", "m.subject")
            .replace("predicate", "m.predicate")
            .replace("sensitivity", "m.sensitivity")
            .replace("review_status", "m.review_status")
            .replace("lifecycle_status", "m.lifecycle_status")
        ).fetchone()[0]
    )
    invalid_digest = int(
        execute(
            f"SELECT COUNT(*) FROM {_INDEX_TABLE} WHERE revision<>? "
            "OR length(value_hmac)<>? OR value_hmac GLOB '*[^0-9a-f]*'",
            (EXACT_LOOKUP_REVISION, _DIGEST_BYTES * 2),
        ).fetchone()[0]
    )
    if (
        active_count != total_indexed
        or joined_count != active_count
        or int(meta["indexed_rows"]) != active_count
        or invalid_digest != 0
    ):
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup sidecar is stale or incomplete"
        )


def _refresh_indexed_count(
    execute: Callable[..., sqlite3.Cursor],
    *,
    now: float,
) -> None:
    count = int(execute(f"SELECT COUNT(*) FROM {_INDEX_TABLE}").fetchone()[0])
    changed = execute(
        f"UPDATE {_META_TABLE} SET indexed_rows=?,updated_at=? WHERE id=? "
        "AND state='completed' AND revision=?",
        (count, now, EXACT_LOOKUP_ID, EXACT_LOOKUP_REVISION),
    ).rowcount
    if changed != 1:
        raise ProtectedMemoryExactLookupError(
            "protected exact lookup metadata changed during write"
        )


def _open_row_value(row: sqlite3.Row, codec: MemoryProtectionCodec) -> str:
    if (
        row["protection_state"] != "protected"
        or row["value"] != ""
        or row["source_ref"] is not None
        or not isinstance(row["value_protected"], str)
        or not row["value_protected"]
    ):
        raise ProtectedMemoryExactLookupError(
            f"protected exact lookup cannot index unsafe row {row['id']}"
        )
    try:
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
    except MemoryProtectionError as exc:
        raise ProtectedMemoryExactLookupError(
            f"protected exact lookup could not open row {row['id']}"
        ) from exc


def _value_digest(key: bytes, value: str) -> str:
    raw = _clean_value(value).encode("utf-8", errors="strict")
    framed = (
        EXACT_LOOKUP_SCHEMA.encode("ascii")
        + b"\x00"
        + VERBATIM_USER_SUBJECT.encode("utf-8")
        + b"\x00"
        + VERBATIM_USER_PREDICATE.encode("utf-8")
        + b"\x00"
        + len(raw).to_bytes(8, "big")
        + raw
    )
    return hmac.new(key, framed, hashlib.sha256).hexdigest()


def _qualifies(
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


def _clean_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 100:
        raise ProtectedMemoryExactLookupError("memory id is invalid")
    return value


def _clean_value(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProtectedMemoryExactLookupError("protected exact lookup value is invalid")
    if len(value) > 50_000:
        raise ProtectedMemoryExactLookupError("protected exact lookup value is too large")
    return value


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtectedMemoryExactLookupError("protected exact lookup limit must be an integer")
    if value < 1 or value > MAX_EXACT_LOOKUP_MATCHES:
        raise ProtectedMemoryExactLookupError(
            f"protected exact lookup limit must be 1..{MAX_EXACT_LOOKUP_MATCHES}"
        )
    return value


_QUALIFYING_SQL = (
    "subject='" + VERBATIM_USER_SUBJECT + "' AND "
    "predicate='" + VERBATIM_USER_PREDICATE + "' AND "
    "sensitivity='private' AND review_status IN ('pending','confirmed') AND "
    "lifecycle_status='active'"
)
