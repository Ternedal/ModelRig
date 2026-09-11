from __future__ import annotations

import hashlib
import hmac
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_protected_lookup import ProtectedMemoryVerbatimLookupMigrator
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator


class TestAeadProvider:
    provider_id = "test-protected-lookup-cross-store-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-lookup-cross-store-provider-key-v1"):
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
            raise MemoryProtectionError("cross-store ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("cross-store ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def prepare(path: Path, value: str, source_ref: str) -> str:
    store = MemoryStore(str(path))
    try:
        memory_id = store.create(
            subject="user",
            predicate="verbatim_user_statement",
            value=value,
            kind="note",
            sensitivity="private",
            source_type="user_explicit",
            source_ref=source_ref,
            confidence=1.0,
            review_status="confirmed",
        ).id
    finally:
        store.close()

    provider = TestAeadProvider()
    codec = MemoryProtectionCodec(provider)
    check(
        MemoryProtectionMigrator(path, codec).migrate().complete,
        f"base migration completes for {path.name}",
    )
    check(
        ProtectedMemoryVerbatimLookupMigrator(path, codec).migrate().complete,
        f"blind-index migration completes for {path.name}",
    )
    return memory_id


def digest(path: Path, memory_id: str) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT value_hmac FROM agent_memory_protected_verbatim_lookup "
            "WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


root = Path(tempfile.mkdtemp(prefix="memory4-protected-lookup-cross-store-"))
first_path = root / "first.db"
second_path = root / "second.db"
value = "W02-CROSS-STORE-EQUALITY-DO-NOT-EXPOSE-77ad"

first_id = prepare(first_path, value, "conversation:first-store")
second_id = prepare(second_path, value, "conversation:second-store")
first_digest = digest(first_path, first_id)
second_digest = digest(second_path, second_id)

check(
    len(first_digest) == 64 and len(second_digest) == 64,
    "both stores persist fixed-size blind fingerprints",
)
check(
    first_digest != second_digest,
    "equal verbatim values in separate stores do not expose cross-store equality",
)
check(
    first_digest != hashlib.sha256(value.encode()).hexdigest()
    and second_digest != hashlib.sha256(value.encode()).hexdigest(),
    "neither store uses an unkeyed value digest",
)

print(
    f"\n===== W02 PROTECTED LOOKUP CROSS-STORE: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
