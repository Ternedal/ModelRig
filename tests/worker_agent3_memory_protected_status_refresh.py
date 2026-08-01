#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import itertools
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_reader import ProtectedMemoryReader  # noqa: E402
from app.agent3.memory_protected_writer import (  # noqa: E402
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class TestAeadProvider:
    provider_id = "test-protected-status-refresh-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-status-refresh-test-key"):
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
            raise MemoryProtectionError("status fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("status fixture authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


with tempfile.TemporaryDirectory(prefix="kaliv-protected-status-refresh-") as tmp:
    database = Path(tmp) / "memory.db"
    legacy = MemoryStore(str(database))
    try:
        legacy.create(
            subject="ModelRig",
            predicate="status_public",
            value="PUBLIC-STATUS-FIXTURE",
            sensitivity="public",
        )
        legacy.create(
            subject="Anders",
            predicate="status_private",
            value="PRIVATE-STATUS-FIXTURE",
            sensitivity="private",
        )
    finally:
        legacy.close()

    migration = MemoryProtectionMigrator(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(migration.complete, "status fixture migration completes")

    reader = ProtectedMemoryReader(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    ids = iter(("status-created-001", "status-corrected-002"))
    timestamps = itertools.count(20_000)
    writer = ProtectedMemoryWriter(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: next(ids),
        clock=lambda: float(next(timestamps)),
    )
    try:
        initial = reader.status
        check(
            initial.protected_rows == 1
            and initial.redacted_rows == 0
            and initial.public_operational_rows == 1,
            "initial status reports migrated row counts",
        )

        created = writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="Anders",
            predicate="status_created",
            value="STATUS-CREATED-VALUE",
            sensitivity="private",
        )
        after_create = reader.status
        check(
            after_create.protected_rows == initial.protected_rows + 1
            and after_create.redacted_rows == initial.redacted_rows
            and after_create.public_operational_rows
            == initial.public_operational_rows,
            "status refreshes protected count after create",
        )

        corrected = writer.correct(
            created.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=created.updated_at,
            value="STATUS-CORRECTED-VALUE",
        )
        after_correct = reader.status
        check(
            after_correct.protected_rows == initial.protected_rows + 2
            and after_correct.redacted_rows == initial.redacted_rows,
            "status refreshes protected count after correction",
        )

        writer.delete(
            corrected.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=corrected.updated_at,
        )
        after_delete = reader.status
        check(
            after_delete.protected_rows == initial.protected_rows + 1
            and after_delete.redacted_rows == initial.redacted_rows + 1
            and after_delete.public_operational_rows
            == initial.public_operational_rows,
            "status refreshes protected and redacted counts after delete",
        )
        check(
            after_delete.schema == initial.schema
            and after_delete.migration_id == initial.migration_id
            and after_delete.provider == initial.provider
            and after_delete.key_scope == initial.key_scope
            and after_delete.migration_state == initial.migration_state
            and after_delete.query_only is True,
            "status preserves validated migration and query-only metadata",
        )
    finally:
        writer.close()
        reader.close()

print(
    f"\n===== AGENT3 PROTECTED MEMORY STATUS REFRESH: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
