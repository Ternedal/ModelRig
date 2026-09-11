from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from typing import Callable

from .memory_protection import MemoryProtectionCodec, MemoryProtectionError


LOOKUP_SCHEMA = "kaliv-agent3-memory-protected-exact-lookup/v1"
LOOKUP_MIGRATION_ID = "agent3-memory-protected-exact-lookup-v1"
LOOKUP_STATE_TABLE = "agent_memory_protected_lookup_migrations"
LOOKUP_COLUMN = "value_lookup_hmac"
LOOKUP_INDEX = "idx_agent_memories_protected_exact_lookup_v1"
LOOKUP_REVISION = 1
LOOKUP_KEY_BYTES = 32
LOOKUP_DIGEST_HEX_CHARS = 64
LOOKUP_STATES = frozenset({"running", "completed"})

_LOOKUP_KEY_ENTROPY = hashlib.sha256(
    b"kaliv-agent3-memory-protected-exact-lookup-key/v1"
).digest()
_LOOKUP_STATE_COLUMNS = {
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


class ProtectedMemoryLookupError(RuntimeError):
    """The protected exact-match index cannot be trusted or opened safely."""


class ProtectedMemoryExactLookup:
    """Current-user-bound keyed equality lookup for protected memory values.

    The durable database stores only a domain-separated HMAC. The random HMAC
    key is itself protected by the same current-user protection provider used by
    protected memory. The key never becomes part of a receipt, API projection or
    model context.
    """

    def __init__(self, key: bytearray):
        if not isinstance(key, bytearray) or len(key) != LOOKUP_KEY_BYTES:
            raise ProtectedMemoryLookupError("protected lookup key size is invalid")
        self._key = key
        self._closed = False

    @classmethod
    def load_if_available(
        cls,
        conn: sqlite3.Connection,
        codec: MemoryProtectionCodec,
    ) -> "ProtectedMemoryExactLookup | None":
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(agent_memories)")
        }
        has_column = LOOKUP_COLUMN in columns
        has_table = _table_exists(conn, LOOKUP_STATE_TABLE)
        has_index = _index_exists(conn, LOOKUP_INDEX)
        artifacts = (has_column, has_table, has_index)
        if not any(artifacts):
            return None
        if not all(artifacts):
            raise ProtectedMemoryLookupError(
                "protected exact lookup migration is only partially installed"
            )
        state_columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({LOOKUP_STATE_TABLE})")
        }
        if state_columns != _LOOKUP_STATE_COLUMNS:
            raise ProtectedMemoryLookupError(
                "protected exact lookup migration table schema mismatch"
            )
        row = conn.execute(
            f"SELECT * FROM {LOOKUP_STATE_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
        if row is None:
            raise ProtectedMemoryLookupError(
                "protected exact lookup migration receipt is missing"
            )
        _validate_state_row(row, codec, require_completed=True)

        # A completed receipt is not enough authority to trust an equality
        # selector forever. A database could later be touched by older code,
        # manual repair or a partial restore. Prove the cheap metadata invariant
        # at writer startup: every currently eligible row has a digest and no
        # ineligible row retains one. This performs no decryption and prevents a
        # missing index entry from becoming a false "no exact match" result.
        missing = conn.execute(
            f"SELECT 1 FROM agent_memories WHERE sensitivity='private' "
            "AND lifecycle_status='active' AND protection_state='protected' "
            f"AND {LOOKUP_COLUMN} IS NULL LIMIT 1"
        ).fetchone()
        if missing is not None:
            raise ProtectedMemoryLookupError(
                "completed protected exact lookup has an unindexed active private row"
            )
        stale = conn.execute(
            f"SELECT 1 FROM agent_memories WHERE {LOOKUP_COLUMN} IS NOT NULL AND NOT ("
            "sensitivity='private' AND lifecycle_status='active' "
            "AND protection_state='protected') LIMIT 1"
        ).fetchone()
        if stale is not None:
            raise ProtectedMemoryLookupError(
                "completed protected exact lookup retains an ineligible digest"
            )
        return cls(_unwrap_lookup_key(codec, row))

    def close(self) -> None:
        if self._closed:
            return
        _wipe(self._key)
        self._closed = True

    def digest(self, *, subject: str, predicate: str, value: str) -> str:
        if self._closed:
            raise ProtectedMemoryLookupError("protected exact lookup is closed")
        payload = _lookup_bytes(subject=subject, predicate=predicate, value=value)
        return hmac.new(bytes(self._key), payload, hashlib.sha256).hexdigest()


def new_wrapped_lookup_key(
    codec: MemoryProtectionCodec,
    *,
    key_factory: Callable[[int], bytes] = secrets.token_bytes,
) -> tuple[bytearray, bytes, str]:
    try:
        generated = key_factory(LOOKUP_KEY_BYTES)
    except Exception as exc:
        raise ProtectedMemoryLookupError("protected lookup key generation failed") from exc
    if not isinstance(generated, bytes) or len(generated) != LOOKUP_KEY_BYTES:
        raise ProtectedMemoryLookupError("protected lookup key generator returned invalid bytes")
    key = bytearray(generated)
    try:
        try:
            ciphertext = codec.provider.protect(
                bytes(key),
                entropy=_LOOKUP_KEY_ENTROPY,
            )
        except MemoryProtectionError:
            raise
        except Exception as exc:
            raise MemoryProtectionError("lookup key protection provider failed") from exc
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ProtectedMemoryLookupError(
                "protected lookup key provider returned no ciphertext"
            )
        return key, ciphertext, hashlib.sha256(ciphertext).hexdigest()
    except Exception:
        _wipe(key)
        raise


def validate_lookup_digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != LOOKUP_DIGEST_HEX_CHARS
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProtectedMemoryLookupError("protected lookup digest is invalid")
    return value


def validate_lookup_state_row(
    row: sqlite3.Row,
    codec: MemoryProtectionCodec,
    *,
    require_completed: bool,
) -> None:
    _validate_state_row(row, codec, require_completed=require_completed)


def unwrap_lookup_key(
    codec: MemoryProtectionCodec,
    row: sqlite3.Row,
) -> bytearray:
    return _unwrap_lookup_key(codec, row)


def _validate_state_row(
    row: sqlite3.Row,
    codec: MemoryProtectionCodec,
    *,
    require_completed: bool,
) -> None:
    if row["schema"] != LOOKUP_SCHEMA or row["id"] != LOOKUP_MIGRATION_ID:
        raise ProtectedMemoryLookupError("protected lookup migration identity mismatch")
    if row["provider"] != codec.provider.provider_id:
        raise ProtectedMemoryLookupError("protected lookup provider mismatch")
    if row["key_scope"] != codec.provider.key_scope:
        raise ProtectedMemoryLookupError("protected lookup key scope mismatch")
    if row["state"] not in LOOKUP_STATES:
        raise ProtectedMemoryLookupError("protected lookup migration state is invalid")
    if require_completed and row["state"] != "completed":
        raise ProtectedMemoryLookupError("protected lookup migration is not complete")
    if int(row["revision"]) != LOOKUP_REVISION:
        raise ProtectedMemoryLookupError("protected lookup revision mismatch")
    for name in ("indexed_rows", "remaining_rows"):
        value = row[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProtectedMemoryLookupError(
                f"protected lookup {name} is invalid"
            )
    if row["state"] == "completed" and int(row["remaining_rows"]) != 0:
        raise ProtectedMemoryLookupError(
            "completed protected lookup migration still has missing rows"
        )
    ciphertext = row["key_ciphertext"]
    if not isinstance(ciphertext, bytes) or not ciphertext:
        raise ProtectedMemoryLookupError("protected lookup key ciphertext is missing")
    digest = row["key_ciphertext_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != LOOKUP_DIGEST_HEX_CHARS
        or any(char not in "0123456789abcdef" for char in digest)
        or hashlib.sha256(ciphertext).hexdigest() != digest
    ):
        raise ProtectedMemoryLookupError(
            "protected lookup key ciphertext digest mismatch"
        )


def _unwrap_lookup_key(
    codec: MemoryProtectionCodec,
    row: sqlite3.Row,
) -> bytearray:
    _validate_state_row(row, codec, require_completed=False)
    ciphertext = bytes(row["key_ciphertext"])
    try:
        clear = codec.provider.unprotect(
            ciphertext,
            entropy=_LOOKUP_KEY_ENTROPY,
        )
    except MemoryProtectionError:
        raise
    except Exception as exc:
        raise ProtectedMemoryLookupError(
            "protected lookup key could not be opened"
        ) from exc
    if not isinstance(clear, bytes) or len(clear) != LOOKUP_KEY_BYTES:
        raise ProtectedMemoryLookupError("unprotected lookup key size is invalid")
    return bytearray(clear)


def _lookup_bytes(*, subject: str, predicate: str, value: str) -> bytes:
    for name, item, maximum in (
        ("subject", subject, 200),
        ("predicate", predicate, 200),
        ("value", value, 64_000),
    ):
        if not isinstance(item, str) or not item or len(item) > maximum:
            raise ProtectedMemoryLookupError(
                f"protected lookup {name} is invalid"
            )
    return json.dumps(
        {
            "namespace": "agent3-memory-protected-exact-lookup",
            "predicate": predicate,
            "revision": LOOKUP_REVISION,
            "subject": subject,
            "value": value,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _index_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
