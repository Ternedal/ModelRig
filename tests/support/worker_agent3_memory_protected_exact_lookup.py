from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_writer import (
    MemoryConsolidationWriteError,
    apply_protected_consolidation_plan,
)
from app.agent3.memory_protected_lookup import (
    LOOKUP_COLUMN,
    LOOKUP_MIGRATION_ID,
    LOOKUP_STATE_TABLE,
)
from app.agent3.memory_protected_lookup_migration import ProtectedMemoryLookupMigrator
from app.agent3.memory_protected_writer import (
    MemoryWriteAccess,
    ProtectedMemoryWriteError,
    ProtectedMemoryWriter,
)
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


class TestAeadProvider:
    provider_id = "test-protected-lookup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"protected-lookup-test-provider-key"):
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
            raise MemoryProtectionError("test lookup ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("test lookup authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


def confirmed_verbatim(value: str, source_ref: str) -> MemoryCandidate:
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


def seed_verbatim_history(path: Path, count: int) -> list[str]:
    store = MemoryStore(str(path))
    values: list[str] = []
    try:
        for index in range(count):
            value = f"Historical protected statement {index:03d}"
            values.append(value)
            store.create(
                subject="user",
                predicate="verbatim_user_statement",
                value=value,
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref=f"conversation:history-{index:03d}",
                confidence=1.0,
                review_status="confirmed",
            )
    finally:
        store.close()
    return values


def complete_base_protection(path: Path, codec: MemoryProtectionCodec) -> None:
    summary = MemoryProtectionMigrator(path, codec).migrate()
    check(summary.complete, "base protected-memory migration completes")


def row_digest(path: Path, memory_id: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            f"SELECT {LOOKUP_COLUMN} FROM agent_memories WHERE id=?",
            (memory_id,),
        ).fetchone()[0]
    finally:
        conn.close()


with tempfile.TemporaryDirectory(prefix="kaliv-w02c-lookup-") as raw:
    root = Path(raw)
    path = root / "memory.db"
    history = seed_verbatim_history(path, 140)
    codec = MemoryProtectionCodec(TestAeadProvider())
    complete_base_protection(path, codec)

    candidate = confirmed_verbatim(
        "A new protected statement beyond the old bound",
        "conversation:w02c-new",
    )
    create_plan = MemoryConsolidator().plan([candidate], [])
    pre_index_writer = ProtectedMemoryWriter(path, MemoryProtectionCodec(TestAeadProvider()))
    try:
        expect_error(
            "pre-index protected W02-B remains fail-closed above the 128-row verbatim bound",
            lambda: apply_protected_consolidation_plan(
                pre_index_writer,
                create_plan,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            ),
            MemoryConsolidationWriteError,
        )
    finally:
        pre_index_writer.close()

    lookup_summary = ProtectedMemoryLookupMigrator(
        path,
        MemoryProtectionCodec(TestAeadProvider()),
        key_factory=lambda size: b"L" * size,
    ).migrate()
    check(
        lookup_summary.complete
        and lookup_summary.indexed_rows == 140
        and lookup_summary.remaining_rows == 0,
        "lookup migration indexes all 140 active private rows and completes",
    )

    raw_db = sqlite3.connect(path)
    raw_db.row_factory = sqlite3.Row
    try:
        rows = raw_db.execute(
            f"SELECT value,{LOOKUP_COLUMN} FROM agent_memories "
            "WHERE subject='user' AND predicate='verbatim_user_statement'"
        ).fetchall()
        state = raw_db.execute(
            f"SELECT * FROM {LOOKUP_STATE_TABLE} WHERE id=?",
            (LOOKUP_MIGRATION_ID,),
        ).fetchone()
    finally:
        raw_db.close()
    check(
        len(rows) == 140
        and all(row["value"] == "" for row in rows)
        and all(
            isinstance(row[LOOKUP_COLUMN], str) and len(row[LOOKUP_COLUMN]) == 64
            for row in rows
        ),
        "lookup migration stores only fixed-size digests beside empty plaintext values",
    )
    first_plain_sha = hashlib.sha256(history[0].encode("utf-8")).hexdigest()
    check(
        rows[0][LOOKUP_COLUMN] != first_plain_sha,
        "stored lookup digest is not an unkeyed SHA-256 of the memory value",
    )
    check(
        isinstance(state["key_ciphertext"], bytes)
        and b"L" * 32 not in state["key_ciphertext"],
        "lookup HMAC key is stored only through the protection provider",
    )

    writer = ProtectedMemoryWriter(path, MemoryProtectionCodec(TestAeadProvider()))
    try:
        created = apply_protected_consolidation_plan(
            writer,
            create_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
        check(
            created.created_count == 1,
            "indexed protected W02-B creates beyond 128 historical verbatim statements",
        )
        created_id = created.created_ids[0]
        created_digest = row_digest(path, created_id)
        check(
            isinstance(created_digest, str) and len(created_digest) == 64,
            "new protected private writes receive an exact-match digest atomically",
        )
        replay = apply_protected_consolidation_plan(
            writer,
            create_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
        check(
            replay.replayed and replay.deduped_ids == (created_id,),
            "indexed protected exact replay resolves without scanning verbatim history",
        )

        pending = writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="user",
            predicate="verbatim_user_statement",
            value="I use the protected lookup index",
            kind="note",
            sensitivity="private",
            source_type="inferred",
            source_ref="run:w02c-pending",
            confidence=0.5,
            review_status="pending",
        )
        confirmed = confirmed_verbatim(
            pending.value,
            "conversation:w02c-promotion",
        )
        promotion_plan = MemoryConsolidator().plan([confirmed], [pending])
        promoted = apply_protected_consolidation_plan(
            writer,
            promotion_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
        promoted_id = promoted.superseding_ids[0]
        check(
            row_digest(path, pending.id) is None
            and isinstance(row_digest(path, promoted_id), str),
            "W02-B promotion clears the old digest and indexes the new active version",
        )

        managed = writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="anders",
            predicate="lookup_lifecycle",
            value="version one",
            sensitivity="private",
            source_type="inferred",
            source_ref="run:w02c-managed",
            review_status="pending",
        )
        corrected = writer.correct(
            managed.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=managed.updated_at,
            value="version two",
            source_ref="conversation:w02c-corrected",
        )
        check(
            row_digest(path, managed.id) is None
            and isinstance(row_digest(path, corrected.id), str),
            "protected correction moves lookup authority to the new active version",
        )
        writer.delete(
            corrected.id,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            expected_updated_at=corrected.updated_at,
        )
        check(
            row_digest(path, corrected.id) is None,
            "protected delete removes the equality digest with the payload",
        )

        secret = writer.create(
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            subject="user",
            predicate="credential",
            value="never-index-this-secret",
            sensitivity="secret",
            source_type="inferred",
            source_ref="run:w02c-secret",
            review_status="pending",
        )
        check(
            row_digest(path, secret.id) is None,
            "secret protected memory never receives an equality digest",
        )
    finally:
        writer.close()

with tempfile.TemporaryDirectory(prefix="kaliv-w02c-partial-") as raw:
    path = Path(raw) / "memory.db"
    seed = MemoryStore(str(path))
    try:
        for index in range(3):
            seed.create(
                subject="user",
                predicate="verbatim_user_statement",
                value=f"partial lookup statement {index}",
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref=f"conversation:partial-{index}",
                review_status="confirmed",
            )
    finally:
        seed.close()
    complete_base_protection(path, MemoryProtectionCodec(TestAeadProvider()))
    partial = ProtectedMemoryLookupMigrator(
        path,
        MemoryProtectionCodec(TestAeadProvider()),
        key_factory=lambda size: b"P" * size,
    ).migrate(batch_limit=1, finalize=False)
    check(
        not partial.complete and partial.remaining_rows == 2,
        "lookup migration can stop after a bounded batch without claiming completion",
    )
    expect_error(
        "protected writer refuses partially migrated lookup state",
        lambda: ProtectedMemoryWriter(path, MemoryProtectionCodec(TestAeadProvider())),
        ProtectedMemoryWriteError,
    )
    resumed = ProtectedMemoryLookupMigrator(
        path,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(
        resumed.complete and resumed.remaining_rows == 0,
        "lookup migration resumes with the same protected per-store key",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-w02c-dpapi-") as raw:
        path = Path(raw) / "memory.db"
        store = MemoryStore(str(path))
        try:
            store.create(
                subject="user",
                predicate="verbatim_user_statement",
                value="Real DPAPI lookup statement",
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref="conversation:w02c-dpapi",
                review_status="confirmed",
            )
        finally:
            store.close()
        complete_base_protection(
            path,
            MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        )
        dpapi_lookup = ProtectedMemoryLookupMigrator(
            path,
            MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        ).migrate()
        check(
            dpapi_lookup.complete and dpapi_lookup.indexed_rows == 1,
            "real Windows DPAPI protects and reopens the per-store lookup key",
        )
        dpapi_writer = ProtectedMemoryWriter(
            path,
            MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        )
        try:
            check(
                dpapi_writer._lookup is not None,
                "real Windows DPAPI store opens the completed exact-match index",
            )
        finally:
            dpapi_writer.close()
else:
    check(True, "real DPAPI lookup qualification is Windows-only")

print(f"\n===== M4 PROTECTED EXACT LOOKUP: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
