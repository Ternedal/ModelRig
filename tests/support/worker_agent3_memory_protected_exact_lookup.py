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
from app.agent3.memory_protected_exact_lookup import (
    EXACT_LOOKUP_ID,
    EXACT_LOOKUP_REVISION,
    EXACT_LOOKUP_SCHEMA,
    ProtectedMemoryExactLookupError,
    ProtectedMemoryExactLookupMigrator,
)
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
    provider_id = "test-protected-exact-lookup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"w02-protected-lookup-test-key-not-production"):
        self.key = key
        self.protect_calls = 0
        self.fail_on_protect_call: int | None = None

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
        self.protect_calls += 1
        if self.protect_calls == self.fail_on_protect_call:
            raise MemoryProtectionError("injected exact-lookup protection failure")
        nonce = hashlib.sha256(
            self.key + entropy + self.protect_calls.to_bytes(8, "big")
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
            raise MemoryProtectionError("exact-lookup ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("exact-lookup ciphertext authentication failed")
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


def plan(candidates, existing=()):
    return MemoryConsolidator().plan(candidates, existing)


def db_counts(path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(path)
    try:
        memories = int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
        indexed = int(
            conn.execute(
                "SELECT COUNT(*) FROM agent_memory_protected_exact_lookup"
            ).fetchone()[0]
        )
        return memories, indexed
    finally:
        conn.close()


def indexed_digest(path: Path, memory_id: str) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT value_hmac FROM agent_memory_protected_exact_lookup "
            "WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


def sidecar_has(path: Path, memory_id: str) -> bool:
    conn = sqlite3.connect(path)
    try:
        return (
            conn.execute(
                "SELECT 1 FROM agent_memory_protected_exact_lookup WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


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


def seed_store(path: Path, provider: TestAeadProvider):
    store = MemoryStore(str(path))
    seeded: list[tuple[str, str, str]] = []
    try:
        for index in range(140):
            value = f"W02-PROTECTED-HISTORY-{index:03d}-7f2b"
            source_ref = f"conversation:protected-history-{index:03d}"
            record = store.create(
                subject="user",
                predicate="verbatim_user_statement",
                value=value,
                kind="note",
                sensitivity="private",
                source_type="user_explicit",
                source_ref=source_ref,
                confidence=1.0,
                review_status="confirmed",
            )
            seeded.append((record.id, value, source_ref))
        pending_value = "W02-PROTECTED-PENDING-PROMOTION-c2a9"
        pending = store.create(
            subject="user",
            predicate="verbatim_user_statement",
            value=pending_value,
            kind="note",
            sensitivity="private",
            source_type="user_explicit",
            source_ref="conversation:protected-pending",
            confidence=0.9,
            review_status="pending",
        )
    finally:
        store.close()
    base = MemoryProtectionMigrator(path, MemoryProtectionCodec(provider)).migrate()
    check(base.complete, "base protected-memory migration completes")
    return seeded, pending.id, pending_value


root = Path(tempfile.mkdtemp(prefix="w02-protected-exact-lookup-"))
path = root / "memory.db"
provider = TestAeadProvider()
codec = MemoryProtectionCodec(provider)
seeded, pending_id, pending_value = seed_store(path, provider)

new_value = "W02-PROTECTED-NEW-AFTER-128-51d4"
new_candidate = confirmed(new_value, "conversation:protected-new")
new_plan = plan([new_candidate])
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "landed W02-B fails closed instead of scanning >128 protected verbatim rows",
        lambda: apply_protected_consolidation_plan(
            writer,
            new_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        MemoryConsolidationWriteError,
    )

summary = ProtectedMemoryExactLookupMigrator(path, codec).migrate()
check(
    summary.complete
    and summary.schema == EXACT_LOOKUP_SCHEMA
    and summary.lookup_id == EXACT_LOOKUP_ID
    and summary.revision == EXACT_LOOKUP_REVISION
    and summary.indexed_rows == 141,
    "explicit exact-lookup migration indexes the complete active canonical set",
)

conn = sqlite3.connect(path)
try:
    meta = conn.execute(
        "SELECT schema,provider,key_scope,state,indexed_rows,revision,key_protected "
        "FROM agent_memory_protected_exact_lookup_meta WHERE id=?",
        (EXACT_LOOKUP_ID,),
    ).fetchone()
    digest_rows = conn.execute(
        "SELECT value_hmac,revision FROM agent_memory_protected_exact_lookup"
    ).fetchall()
finally:
    conn.close()
check(
    meta is not None
    and meta[0] == EXACT_LOOKUP_SCHEMA
    and meta[3] == "completed"
    and int(meta[4]) == 141
    and int(meta[5]) == EXACT_LOOKUP_REVISION,
    "sidecar metadata is versioned and completed",
)
check(
    len(digest_rows) == 141
    and all(len(str(row[0])) == 64 and int(row[1]) == EXACT_LOOKUP_REVISION for row in digest_rows),
    "sidecar stores only fixed-size keyed digests",
)
raw = family_bytes(path)
check(
    new_value.encode() not in raw
    and pending_value.encode() not in raw
    and all(value.encode() not in raw for _id, value, _source in seeded[:5]),
    "protected database family contains no sampled verbatim plaintext",
)
first_id, first_value, first_source = seeded[0]
check(
    indexed_digest(path, first_id) != hashlib.sha256(first_value.encode()).hexdigest(),
    "exact-match digest is not an unkeyed plaintext hash",
)

# The indexed composition now scales past 128 distinct canonical statements.
with ProtectedMemoryWriter(path, codec) as writer:
    receipt = apply_indexed_protected_consolidation_plan(
        writer,
        new_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    receipt.created_count == 1 and not receipt.replayed,
    "indexed W02 creates a distinct canonical statement beyond 128 history rows",
)
new_id = receipt.created_ids[0]
check(sidecar_has(path, new_id), "indexed W02 create updates the sidecar atomically")

# Exact replay is still proven by decrypting the selected durable row, not by HMAC alone.
with ProtectedMemoryWriter(path, codec) as writer:
    replay = apply_indexed_protected_consolidation_plan(
        writer,
        new_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    replay.replayed and replay.deduped_ids == (new_id,),
    "indexed W02 exact replay remains idempotent",
)

# A pre-store dedupe plan for an older exact value remains valid beyond the old bound.
with ProtectedMemoryReader(path, codec) as reader:
    first_record = reader.get(first_id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
first_candidate = confirmed(first_value, first_source)
dedupe_plan = plan([first_candidate], [first_record])
with ProtectedMemoryWriter(path, codec) as writer:
    dedupe = apply_indexed_protected_consolidation_plan(
        writer,
        dedupe_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    dedupe.deduped_ids == (first_id,) and dedupe.created_count == 0,
    "indexed selector finds an old exact value without decrypting unrelated history",
)

# Exact pending -> confirmed promotion keeps version semantics and moves the index row.
with ProtectedMemoryReader(path, codec) as reader:
    pending_record = reader.get(pending_id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
promotion_candidate = confirmed(
    pending_value,
    "conversation:protected-promotion-confirmed",
)
promotion_plan = plan([promotion_candidate], [pending_record])
with ProtectedMemoryWriter(path, codec) as writer:
    promoted = apply_indexed_protected_consolidation_plan(
        writer,
        promotion_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    promoted.superseded_ids == (pending_id,)
    and len(promoted.superseding_ids) == 1,
    "indexed W02 preserves exact pending-to-confirmed version promotion",
)
promoted_id = promoted.superseding_ids[0]
check(
    not sidecar_has(path, pending_id) and sidecar_has(path, promoted_id),
    "supersede removes the inactive predecessor from the exact-match sidecar",
)

# Missing/stale index data must never become a false negative.
conn = sqlite3.connect(path)
try:
    conn.execute(
        "DELETE FROM agent_memory_protected_exact_lookup WHERE memory_id=?",
        (first_id,),
    )
    conn.commit()
finally:
    conn.close()
before_stale = db_counts(path)
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "incomplete sidecar fails closed before W02 mutation",
        lambda: apply_indexed_protected_consolidation_plan(
            writer,
            plan([confirmed("W02-STALE-SIDECAR-NEW-82ce", "conversation:stale")]),
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        MemoryConsolidationWriteError,
    )
check(db_counts(path) == before_stale, "stale-sidecar refusal does not mutate memory")

# An explicit rebuild repairs the sidecar with the same protected key material.
repaired = ProtectedMemoryExactLookupMigrator(path, codec).migrate()
check(repaired.complete, "explicit exact-lookup rebuild repairs stale sidecar state")
check(sidecar_has(path, first_id), "rebuild restores the missing exact-match row")

# A generic management write does not silently create a false-negative index. It
# makes completeness fail closed until the explicit sidecar migration is rerun.
with ProtectedMemoryWriter(path, codec) as writer:
    unmanaged = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="user",
        predicate="verbatim_user_statement",
        value="W02-OUT-OF-BAND-CANONICAL-11a7",
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="management:out-of-band",
        confidence=1.0,
        review_status="confirmed",
    )
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "out-of-band canonical management write invalidates sidecar availability",
        lambda: apply_indexed_protected_consolidation_plan(
            writer,
            plan([confirmed("W02-AFTER-OUT-OF-BAND-9e12", "conversation:after-oob")]),
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        MemoryConsolidationWriteError,
    )
check(not sidecar_has(path, unmanaged.id), "out-of-band write cannot forge sidecar authority")
ProtectedMemoryExactLookupMigrator(path, codec).migrate()

# Late encryption failure after an earlier insert rolls back the whole memory batch;
# sidecar state remains unchanged because maintenance shares the same transaction.
rollback_candidates = [
    confirmed("W02-ROLLBACK-A-35c1", "conversation:rollback-a"),
    confirmed("W02-ROLLBACK-B-46d2", "conversation:rollback-b"),
]
rollback_plan = plan(rollback_candidates)
before_failure = db_counts(path)
provider.fail_on_protect_call = provider.protect_calls + 3
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "late protected encryption failure aborts indexed W02 batch",
        lambda: apply_indexed_protected_consolidation_plan(
            writer,
            rollback_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        Exception,
    )
provider.fail_on_protect_call = None
check(
    db_counts(path) == before_failure,
    "late indexed W02 failure rolls back both memory and sidecar state",
)

# Different stores get independent random HMAC secrets even with the same test
# protection provider key; cross-store equality therefore is not exposed.
second_path = root / "memory-second.db"
second_provider = TestAeadProvider(provider.key)
second_codec = MemoryProtectionCodec(second_provider)
second_store = MemoryStore(str(second_path))
try:
    second_row = second_store.create(
        subject="user",
        predicate="verbatim_user_statement",
        value=first_value,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="conversation:second-store",
        confidence=1.0,
        review_status="confirmed",
    )
finally:
    second_store.close()
MemoryProtectionMigrator(second_path, second_codec).migrate()
ProtectedMemoryExactLookupMigrator(second_path, second_codec).migrate()
check(
    indexed_digest(path, first_id) != indexed_digest(second_path, second_row.id),
    "separate protected stores do not expose cross-store equality",
)

# Metadata/envelopes/digests must not accidentally contain known source refs either.
raw = family_bytes(path)
check(
    first_source.encode() not in raw
    and b"conversation:protected-promotion-confirmed" not in raw,
    "exact-match sidecar does not reintroduce plaintext source provenance",
)

print(
    f"\n===== W02 PROTECTED EXACT LOOKUP: {passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
