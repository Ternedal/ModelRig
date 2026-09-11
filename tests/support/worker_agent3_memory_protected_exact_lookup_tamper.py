from __future__ import annotations

import hashlib
import hmac
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_writer import MemoryConsolidationWriteError
from app.agent3.memory_protected_exact_lookup import ProtectedMemoryExactLookupMigrator
from app.agent3.memory_protected_indexed_consolidation import (
    apply_indexed_protected_consolidation_plan,
)
from app.agent3.memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from app.agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import MemoryCandidate, MemoryConsolidator


class TestAeadProvider:
    provider_id = "test-protected-exact-lookup-tamper-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-exact-lookup-tamper-key-v1"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        block = 0
        while len(result) < length:
            result.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(result[:length])

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
            raise MemoryProtectionError("tamper-test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("tamper-test ciphertext authentication failed")
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


def confirmed(value: str, source_ref: str) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=value,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=value,
    )


root = Path(tempfile.mkdtemp(prefix="w02-protected-exact-tamper-"))
path = root / "memory.db"
provider = TestAeadProvider()
codec = MemoryProtectionCodec(provider)

store = MemoryStore(str(path))
try:
    seeded = store.create(
        subject="user",
        predicate="verbatim_user_statement",
        value="W02-BLIND-INDEX-TAMPER-TARGET-91af",
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="conversation:tamper-seed",
        confidence=1.0,
        review_status="confirmed",
    )
finally:
    store.close()
check(
    MemoryProtectionMigrator(path, codec).migrate().complete,
    "tamper fixture base protection migration completes",
)
check(
    ProtectedMemoryExactLookupMigrator(path, codec).migrate().complete,
    "tamper fixture exact-match sidecar migration completes",
)

with ProtectedMemoryReader(path, codec) as reader:
    durable = reader.get(seeded.id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
candidate = confirmed(durable.value, durable.source_ref or "conversation:tamper-seed")
trusted_plan = MemoryConsolidator().plan([candidate], [durable])
check(
    trusted_plan.actions[0].decision == "dedupe"
    and trusted_plan.actions[0].existing_id == seeded.id,
    "fixture begins with a trusted exact dedupe plan",
)

conn = sqlite3.connect(path)
try:
    conn.execute(
        "UPDATE agent_memory_protected_exact_lookup SET value_hmac=? WHERE memory_id=?",
        ("0" * 64, seeded.id),
    )
    conn.commit()
finally:
    conn.close()

refused = False
with ProtectedMemoryWriter(path, codec) as writer:
    try:
        apply_indexed_protected_consolidation_plan(
            writer,
            trusted_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
    except MemoryConsolidationWriteError:
        refused = True
check(
    refused,
    "tampered selector cannot be bypassed by a plan-supplied canonical existing id",
)

conn = sqlite3.connect(path)
try:
    active = int(
        conn.execute(
            "SELECT COUNT(*) FROM agent_memories WHERE id=? AND lifecycle_status='active'",
            (seeded.id,),
        ).fetchone()[0]
    )
finally:
    conn.close()
check(active == 1, "tamper refusal leaves durable memory unchanged")

print(
    f"\n===== W02 PROTECTED EXACT LOOKUP TAMPER: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
