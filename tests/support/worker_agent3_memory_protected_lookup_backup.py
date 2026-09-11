from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_writer import apply_protected_consolidation_plan
from app.agent3.memory_protected_backup import ProtectedMemoryBackupManager
from app.agent3.memory_protected_lookup import LOOKUP_COLUMN
from app.agent3.memory_protected_lookup_migration import ProtectedMemoryLookupMigrator
from app.agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import MemoryCandidate, MemoryConsolidator


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class BackupAeadProvider:
    provider_id = "test-protected-lookup-backup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-lookup-backup-test-key"):
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
            raise MemoryProtectionError("backup test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("backup test authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


def candidate(value: str, source_ref: str) -> MemoryCandidate:
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


def digest_for(path: Path, memory_id: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            f"SELECT {LOOKUP_COLUMN} FROM agent_memories WHERE id=?",
            (memory_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def qualify_backup(provider, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"kaliv-w02c-backup-{label}-") as raw:
        root = Path(raw)
        source = root / "source.db"
        bundle = root / "backup.bundle"
        restored = root / "restored.db"

        seed = MemoryStore(str(source))
        try:
            original = seed.create(
                subject="user",
                predicate="verbatim_user_statement",
                value=f"Protected lookup backup {label}",
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref=f"conversation:w02c-backup-{label}",
                confidence=1.0,
                review_status="confirmed",
            )
        finally:
            seed.close()

        codec = MemoryProtectionCodec(provider())
        base = MemoryProtectionMigrator(source, codec).migrate()
        lookup = ProtectedMemoryLookupMigrator(
            source,
            MemoryProtectionCodec(provider()),
            key_factory=(lambda size: b"B" * size) if label == "test" else None,
        ).migrate()
        check(base.complete and lookup.complete, f"{label} backup fixture migrations complete")
        source_digest = digest_for(source, original.id)

        manager = ProtectedMemoryBackupManager(MemoryProtectionCodec(provider()))
        created = manager.create(source, bundle)
        verified = manager.verify(bundle)
        restored_summary = manager.restore(bundle, restored)
        check(
            created.artifact_sha256 == verified.artifact_sha256
            == restored_summary.artifact_sha256,
            f"{label} backup manifest and restored artifact remain bound",
        )
        check(
            digest_for(restored, original.id) == source_digest,
            f"{label} restore preserves the keyed lookup digest exactly",
        )

        restored_writer = ProtectedMemoryWriter(
            restored,
            MemoryProtectionCodec(provider()),
        )
        try:
            exact = candidate(
                f"Protected lookup backup {label}",
                f"conversation:w02c-backup-{label}",
            )
            exact_plan = MemoryConsolidator().plan([exact], [])
            replay = apply_protected_consolidation_plan(
                restored_writer,
                exact_plan,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            )
            check(
                replay.replayed and replay.deduped_ids == (original.id,),
                f"{label} restored lookup key supports exact W02 replay",
            )
        finally:
            restored_writer.close()


qualify_backup(BackupAeadProvider, "test")

if os.name == "nt":
    qualify_backup(WindowsDpapiMemoryProtectionProvider, "dpapi")
else:
    check(True, "real DPAPI lookup backup/restore qualification is Windows-only")

print(f"\n===== M4 PROTECTED LOOKUP BACKUP: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
