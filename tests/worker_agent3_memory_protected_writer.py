#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import itertools
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryConflict, MemoryNotFound, MemoryStore  # noqa: E402
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReadError,
    ProtectedMemoryReader,
)
from app.agent3.memory_protected_writer import (  # noqa: E402
    MemoryWriteAccess,
    ProtectedMemoryWriteError,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class TestAeadProvider:
    provider_id = "test-protected-writer-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(
        self,
        key: bytes = b"t033-writer-test-key-not-production",
        *,
        fail_on_protect_call: int | None = None,
    ):
        self.key = key
        self.calls = 0
        self.fail_on_protect_call = fail_on_protect_call

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
        if self.calls == self.fail_on_protect_call:
            raise MemoryProtectionError("injected writer protection failure")
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("writer ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("writer ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


VALUES = {
    "seed": "T033-WRITER-SEED-PRIVATE-1f3a",
    "created": "T033-WRITER-CREATED-PRIVATE-2b4c",
    "source": "T033-WRITER-CREATED-SOURCE-3d5e",
    "secret": "T033-WRITER-CREATED-SECRET-4f6a",
    "corrected": "T033-WRITER-CORRECTED-PRIVATE-5b7c",
    "corrected_source": "T033-WRITER-CORRECTED-SOURCE-6d8e",
    "failed": "T033-WRITER-FAILED-PLAINTEXT-7f9a",
}

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_error(label: str, fn, error_type, contains: str | None = None) -> None:
    try:
        fn()
    except error_type as exc:
        check(label, contains is None or contains in str(exc))
    except Exception:
        check(label, False)
    else:
        check(label, False)


def family_bytes(path: Path) -> bytes:
    raw = bytearray()
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if candidate.is_file():
            raw.extend(candidate.read_bytes())
    return bytes(raw)


def no_sensitive_plaintext(path: Path) -> bool:
    raw = family_bytes(path)
    return all(value.encode("utf-8") not in raw for value in VALUES.values())


def seed_and_migrate(path: Path, provider) -> str:
    store = MemoryStore(str(path))
    try:
        seed_id = store.create(
            subject="Anders",
            predicate="writer_seed",
            value=VALUES["seed"],
            sensitivity="private",
        ).id
        store.create(
            subject="system",
            predicate="public_seed",
            value="PUBLIC-WRITER-SEED",
            sensitivity="public",
        )
    finally:
        store.close()
    summary = MemoryProtectionMigrator(
        path,
        MemoryProtectionCodec(provider),
    ).migrate()
    check("writer fixture migration completes", summary.complete)
    return seed_id


def row(path: Path, memory_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        result = conn.execute(
            "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
        ).fetchone()
        assert result is not None
        return result
    finally:
        conn.close()


def row_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        conn.close()


with tempfile.TemporaryDirectory(prefix="kaliv-t033-writer-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed_id = seed_and_migrate(db, TestAeadProvider())
    ids = iter(
        [
            "writer-created-001",
            "writer-secret-002",
            "writer-corrected-003",
            "writer-unused-stale-004",
            "writer-unused-stale-005",
        ]
    )
    clock_values = itertools.count(2_000)
    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: next(ids),
        clock=lambda: float(next(clock_values)),
    )

    created = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        predicate="writer_created",
        value=VALUES["created"],
        sensitivity="private",
        source_ref=VALUES["source"],
    )
    created_row = row(db, created.id)
    check("protected create returns caller value", created.value == VALUES["created"])
    check("protected create stores no plaintext columns", created_row["value"] == "" and created_row["source_ref"] is None)
    check("protected create stores both envelopes", created_row["protection_fields"] == "value,source_ref")
    check("protected create row is protected", created_row["protection_state"] == "protected")

    secret = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        predicate="writer_secret",
        value=VALUES["secret"],
        sensitivity="secret",
        source_type="inferred",
    )
    check("inferred secret defaults pending", secret.review_status == "pending")

    with ProtectedMemoryReader(db, MemoryProtectionCodec(TestAeadProvider())) as reader:
        opened = reader.get(created.id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        check("reader opens newly created private value", opened.value == VALUES["created"])
        check("reader opens newly created source_ref", opened.source_ref == VALUES["source"])
        check(
            "reader keeps new secret redacted in context",
            reader.get(secret.id, access=MemoryReadAccess.LOCAL_CONTEXT).value
            == "[redacted]",
        )

    corrected = writer.correct(
        created.id,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        expected_updated_at=created.updated_at,
        value=VALUES["corrected"],
        source_ref=VALUES["corrected_source"],
    )
    old_row = row(db, created.id)
    new_row = row(db, corrected.id)
    check("correction supersedes old encrypted row", old_row["lifecycle_status"] == "superseded" and old_row["value"] == "")
    check("replacement points to old id", new_row["supersedes_id"] == created.id)
    check("replacement stores no plaintext columns", new_row["value"] == "" and new_row["source_ref"] is None)
    with ProtectedMemoryReader(db, MemoryProtectionCodec(TestAeadProvider())) as reader:
        history = reader.history(
            "Anders",
            "writer_created",
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )
        check(
            "protected correction history opens both versions",
            [item.value for item in history]
            == [VALUES["created"], VALUES["corrected"]],
        )

    before_stale = row_count(db)
    expect_error(
        "stale correction is rejected",
        lambda: writer.correct(
            corrected.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=corrected.updated_at - 1,
            value="STALE-CORRECTION",
        ),
        MemoryConflict,
        "changed",
    )
    check("stale correction rolls back its insert", row_count(db) == before_stale)

    deleted = writer.delete(
        corrected.id,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        expected_updated_at=corrected.updated_at,
    )
    deleted_row = row(db, corrected.id)
    check("protected delete returns payload-free tombstone", deleted.value == "" and deleted.source_ref is None)
    check("protected delete clears both envelopes", deleted_row["value_protected"] is None and deleted_row["source_ref_protected"] is None)
    check("protected delete marks redacted", deleted_row["protection_state"] == "redacted" and deleted_row["protection_fields"] == "")
    expect_error(
        "repeated delete is not reported as success",
        lambda: writer.delete(
            corrected.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=deleted.updated_at,
        ),
        MemoryNotFound,
        "not found",
    )

    expect_error(
        "protected writer refuses public values",
        lambda: writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="system",
            predicate="bad_public",
            value="PUBLIC",
            sensitivity="public",
        ),
        ProtectedMemoryWriteError,
        "sensitivity",
    )
    expect_error(
        "protected writer requires enum access",
        lambda: writer.create(
            access="local_management",  # type: ignore[arg-type]
            subject="Anders",
            predicate="bad_access",
            value="BAD",
        ),
        ProtectedMemoryWriteError,
        "explicit",
    )
    expect_error(
        "stale seed delete is rejected",
        lambda: writer.delete(
            seed_id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=0,
        ),
        MemoryConflict,
        "changed",
    )

    writer.close()
    expect_error(
        "closed writer rejects writes",
        lambda: writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="Anders",
            predicate="closed",
            value="CLOSED",
        ),
        ProtectedMemoryWriteError,
        "closed",
    )
    check("SQLite/WAL/journal family contains no writer plaintext", no_sensitive_plaintext(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-writer-failure-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed_and_migrate(db, TestAeadProvider())
    before = row_count(db)
    failing_writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider(fail_on_protect_call=2)),
        id_factory=lambda: "writer-failed-004",
        clock=lambda: 3_000.0,
    )
    expect_error(
        "source_ref encryption failure writes no partial row",
        lambda: failing_writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="Anders",
            predicate="failed_writer",
            value=VALUES["failed"],
            source_ref="FAILED-SOURCE",
        ),
        ProtectedMemoryWriteError,
        "could not be encrypted",
    )
    failing_writer.close()
    check("failed encryption leaves row count unchanged", before == row_count(db))
    check("failed plaintext never reaches SQLite bytes", VALUES["failed"].encode() not in family_bytes(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-writer-collision-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed_id = seed_and_migrate(db, TestAeadProvider())
    collision = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: seed_id,
    )
    expect_error(
        "id collision rolls back protected insert",
        lambda: collision.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="Anders",
            predicate="collision",
            value="COLLISION-VALUE",
        ),
        MemoryConflict,
        "already exists",
    )
    collision.close()
    check("collision plaintext never reaches SQLite bytes", b"COLLISION-VALUE" not in family_bytes(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-writer-incomplete-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    store = MemoryStore(str(db))
    try:
        store.create(
            subject="Anders",
            predicate="incomplete",
            value="INCOMPLETE",
            sensitivity="private",
        )
    finally:
        store.close()
    MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate(batch_limit=1, finalize=False)
    expect_error(
        "incomplete migration blocks writer startup",
        lambda: ProtectedMemoryWriter(
            db,
            MemoryProtectionCodec(TestAeadProvider()),
        ),
        (ProtectedMemoryReadError, ProtectedMemoryWriteError),
        "not complete",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-t033-writer-dpapi-") as tmp:
        root = Path(tmp)
        db = root / "memory.db"
        provider = WindowsDpapiMemoryProtectionProvider()
        seed_and_migrate(db, provider)
        codec = MemoryProtectionCodec(provider)
        with ProtectedMemoryWriter(
            db,
            codec,
            id_factory=lambda: "windows-writer-001",
            clock=lambda: 4_000.0,
        ) as writer:
            created = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                subject="Anders",
                predicate="windows_writer",
                value=VALUES["created"],
                source_ref=VALUES["source"],
            )
        with ProtectedMemoryReader(db, codec) as reader:
            opened = reader.get(
                created.id,
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
            )
            check("real Windows DPAPI opens protected writer value", opened.value == VALUES["created"])
            check("real Windows DPAPI opens protected writer source_ref", opened.source_ref == VALUES["source"])
        check("real Windows DPAPI writer stores no known plaintext bytes", no_sensitive_plaintext(db))
else:
    check("real DPAPI protected writer is reserved for windows-latest", True)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 PROTECTED MEMORY WRITER: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
