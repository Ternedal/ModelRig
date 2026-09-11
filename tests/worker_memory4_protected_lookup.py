from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_indexed import (
    IndexedMemoryConsolidationWriteError,
    apply_protected_consolidation_plan_indexed,
)
from app.agent3.memory_protected_lookup import (
    LOOKUP_KEY_BYTES,
    LOOKUP_SCHEMA,
    ProtectedMemoryLookupError,
    ProtectedMemoryVerbatimLookup,
    ProtectedMemoryVerbatimLookupMigrator,
)
from app.agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import MemoryCandidate, MemoryConsolidator


class TestAeadProvider:
    provider_id = "test-memory4-lookup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"memory4-lookup-provider-key-v1"):
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
            raise MemoryProtectionError("lookup test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("lookup test ciphertext authentication failed")
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


def expect_error(name, fn, error_type, contains: str | None = None):
    try:
        fn()
    except error_type as exc:
        check(contains is None or contains in str(exc), name)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)


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


def family_bytes(path: Path) -> bytes:
    output = bytearray()
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if candidate.is_file():
            output.extend(candidate.read_bytes())
    return bytes(output)


def active_verbatim_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM agent_memories WHERE subject='user' "
                "AND predicate='verbatim_user_statement' "
                "AND lifecycle_status='active'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


with tempfile.TemporaryDirectory(prefix="memory4-protected-lookup-") as tmp:
    db = Path(tmp) / "memory.db"
    seed = MemoryStore(str(db))
    seed.create(
        subject="seed",
        predicate="private",
        value="seed-private-value",
        sensitivity="private",
        source_type="inferred",
        source_ref="seed:private",
    )
    seed.close()

    base_codec = MemoryProtectionCodec(TestAeadProvider())
    base_migration = MemoryProtectionMigrator(db, base_codec).migrate()
    check(base_migration.complete, "base protected-memory migration completes")

    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    existing = []
    for index in range(140):
        existing.append(
            writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                subject="user",
                predicate="verbatim_user_statement",
                value=f"historical-verbatim-{index:03d}",
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref=f"conversation:history-{index:03d}",
                confidence=1.0,
                review_status="confirmed",
            )
        )
    writer.close()
    check(
        active_verbatim_count(db) == 140,
        "fixture contains more than the old 128-row protected verbatim bound",
    )

    lookup_key = b"K" * LOOKUP_KEY_BYTES
    migrator = ProtectedMemoryVerbatimLookupMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        key_factory=lambda size: lookup_key if size == LOOKUP_KEY_BYTES else b"",
    )
    first = migrator.migrate(batch_limit=50)
    check(
        not first.complete and first.indexed_total == 50 and first.rows_remaining == 90,
        "lookup migration is explicitly resumable after the first bounded batch",
    )
    second = migrator.migrate(batch_limit=50)
    check(
        not second.complete and second.indexed_total == 100 and second.rows_remaining == 40,
        "lookup migration resumes with the same protected key",
    )
    final = migrator.migrate(batch_limit=50)
    check(
        final.complete and final.indexed_total == 140 and final.rows_remaining == 0,
        "lookup migration completes after all historical verbatim rows are indexed",
    )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        lookup_row = conn.execute(
            "SELECT * FROM agent_memory_protected_verbatim_lookup "
            "WHERE memory_id=?",
            (existing[0].id,),
        ).fetchone()
        receipt_row = conn.execute(
            "SELECT * FROM agent_memory_protected_lookup_migrations"
        ).fetchone()
    finally:
        conn.close()
    check(
        lookup_row is not None
        and lookup_row["schema"] == LOOKUP_SCHEMA
        and len(str(lookup_row["value_hmac"])) == 64
        and lookup_row["value_hmac"]
        != hashlib.sha256(existing[0].value.encode()).hexdigest(),
        "SQLite stores a keyed blind fingerprint rather than an unkeyed value hash",
    )
    raw = family_bytes(db)
    check(
        lookup_key not in raw
        and existing[0].value.encode() not in raw
        and receipt_row is not None
        and receipt_row["state"] == "completed",
        "lookup key and protected verbatim plaintext are absent from SQLite family bytes",
    )

    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    candidate_new = confirmed(
        "historical-verbatim-140",
        "conversation:history-140",
    )
    create_plan = MemoryConsolidator().plan([candidate_new], [])
    created = apply_protected_consolidation_plan_indexed(
        writer,
        create_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
    check(
        created.created_count == 1 and active_verbatim_count(db) == 141,
        "indexed W02-B creates beyond 128 protected historical verbatim statements",
    )

    duplicate_candidate = confirmed(
        existing[0].value,
        "conversation:duplicate-replay",
    )
    dedupe_plan = MemoryConsolidator().plan(
        [duplicate_candidate],
        [existing[0]],
    )
    deduped = apply_protected_consolidation_plan_indexed(
        writer,
        dedupe_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
    check(
        deduped.created_count == 0 and deduped.deduped_ids == (existing[0].id,),
        "indexed W02-B exact-match lookup finds a durable row beyond bounded slot history",
    )

    manual = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="user",
        predicate="verbatim_user_statement",
        value="manual-after-index",
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="conversation:manual-after-index",
        confidence=1.0,
        review_status="confirmed",
    )
    manual_candidate = confirmed(
        manual.value,
        "conversation:manual-dedupe",
    )
    manual_plan = MemoryConsolidator().plan([manual_candidate], [manual])
    expect_error(
        "indexed W02-B fails closed when another protected writer leaves canonical history unindexed",
        lambda: apply_protected_consolidation_plan_indexed(
            writer,
            manual_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        IndexedMemoryConsolidationWriteError,
        "incomplete",
    )
    writer.close()

    repaired = migrator.migrate()
    check(
        repaired.complete and repaired.rows_remaining == 0,
        "rerunning the offline lookup migration repairs newly unindexed history",
    )
    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    repaired_dedupe = apply_protected_consolidation_plan_indexed(
        writer,
        manual_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
    check(
        repaired_dedupe.deduped_ids == (manual.id,),
        "indexed W02-B resumes exact dedupe after explicit repair migration",
    )

    rollback_candidate = confirmed(
        "rollback-index-failure",
        "conversation:rollback-index-failure",
    )
    rollback_plan = MemoryConsolidator().plan([rollback_candidate], [])
    before_rollback = active_verbatim_count(db)
    original_index_created = ProtectedMemoryVerbatimLookup.index_created_locked

    def fail_index_created(self, *args, **kwargs):
        raise ProtectedMemoryLookupError("injected lookup index failure")

    ProtectedMemoryVerbatimLookup.index_created_locked = fail_index_created
    try:
        expect_error(
            "late blind-index failure propagates out of indexed W02-B",
            lambda: apply_protected_consolidation_plan_indexed(
                writer,
                rollback_plan,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            ),
            IndexedMemoryConsolidationWriteError,
            "injected lookup index failure",
        )
    finally:
        ProtectedMemoryVerbatimLookup.index_created_locked = original_index_created
    check(
        active_verbatim_count(db) == before_rollback,
        "late blind-index failure rolls back the protected memory insert atomically",
    )

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE agent_memory_protected_verbatim_lookup SET value_hmac=? "
            "WHERE memory_id=?",
            ("0" * 64, existing[1].id),
        )
        conn.commit()
    finally:
        conn.close()
    tampered_candidate = confirmed(
        existing[1].value,
        "conversation:tampered-index",
    )
    tampered_plan = MemoryConsolidator().plan([tampered_candidate], [existing[1]])
    expect_error(
        "a tampered selector cannot satisfy a trusted dedupe plan",
        lambda: apply_protected_consolidation_plan_indexed(
            writer,
            tampered_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        IndexedMemoryConsolidationWriteError,
        "stale or forged",
    )
    writer.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
