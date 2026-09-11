from __future__ import annotations

import hashlib
import hmac
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_protected_lookup import LOOKUP_COLUMN
from app.agent3.memory_protected_lookup_migration import ProtectedMemoryLookupMigrator
from app.agent3.memory_protected_writer import (
    ProtectedMemoryWriteError,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(name, fn, error_type):
    try:
        fn()
    except error_type:
        check(True, name)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)


class DriftAeadProvider:
    provider_id = "test-protected-lookup-drift-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-lookup-drift-test-key"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        block = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(output[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.calls += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("drift test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("drift test authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


def codec() -> MemoryProtectionCodec:
    return MemoryProtectionCodec(DriftAeadProvider())


with tempfile.TemporaryDirectory(prefix="kaliv-w02c-drift-") as raw:
    path = Path(raw) / "memory.db"
    store = MemoryStore(str(path))
    try:
        row = store.create(
            subject="user",
            predicate="verbatim_user_statement",
            value="Protected lookup drift sentinel",
            kind="note",
            sensitivity="private",
            source_type="user_explicit",
            source_ref="conversation:w02c-drift",
            confidence=1.0,
            review_status="confirmed",
        )
    finally:
        store.close()

    base = MemoryProtectionMigrator(path, codec()).migrate()
    lookup = ProtectedMemoryLookupMigrator(
        path,
        codec(),
        key_factory=lambda size: b"D" * size,
    ).migrate()
    check(base.complete and lookup.complete, "drift fixture migrations complete")

    connection = sqlite3.connect(path)
    try:
        before = connection.execute(
            f"SELECT {LOOKUP_COLUMN} FROM agent_memories WHERE id=?",
            (row.id,),
        ).fetchone()[0]
        connection.execute(
            f"UPDATE agent_memories SET {LOOKUP_COLUMN}=NULL WHERE id=?",
            (row.id,),
        )
        connection.commit()
    finally:
        connection.close()
    check(
        isinstance(before, str) and len(before) == 64,
        "completed lookup begins with a durable digest",
    )
    expect_error(
        "writer refuses completed lookup state with a missing active-private digest",
        lambda: ProtectedMemoryWriter(path, codec()),
        ProtectedMemoryWriteError,
    )

    repaired = ProtectedMemoryLookupMigrator(path, codec()).migrate()
    check(
        repaired.complete and repaired.remaining_rows == 0,
        "offline lookup migration repairs missing digest without replacing the store",
    )
    repaired_writer = ProtectedMemoryWriter(path, codec())
    repaired_writer.close()
    check(True, "writer reopens after offline lookup repair")

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            f"UPDATE agent_memories SET lifecycle_status='superseded' WHERE id=?",
            (row.id,),
        )
        connection.commit()
    finally:
        connection.close()
    expect_error(
        "writer refuses an ineligible row that still retains a lookup digest",
        lambda: ProtectedMemoryWriter(path, codec()),
        ProtectedMemoryWriteError,
    )

print(f"\n===== M4 PROTECTED LOOKUP DRIFT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
