from __future__ import annotations

import hashlib
import hmac
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_indexed import (
    IndexedMemoryConsolidationWriteError,
    apply_protected_consolidation_plan_indexed,
)
from app.agent3.memory_consolidation_writer import (
    MemoryConsolidationWriteError,
    apply_protected_consolidation_plan,
)
from app.agent3.memory_protected_lookup import (
    LOOKUP_KEY_BYTES,
    LOOKUP_SCHEMA,
    ProtectedMemoryLookupError,
    ProtectedMemoryVerbatimLookup,
    ProtectedMemoryVerbatimLookupMigrator,
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
    provider_id = "test-memory4-protected-lookup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"memory4-protected-lookup-provider-key-v1"):
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


def sidecar_ids(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT memory_id FROM agent_memory_protected_verbatim_lookup"
            ).fetchall()
        }
    finally:
        conn.close()


def sidecar_digest(path: Path, memory_id: str) -> str:
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


def memory_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        conn.close()


def seed(path: Path):
    store = MemoryStore(str(path))
    history = []
    try:
        for index in range(140):
            value = f"W02-BLIND-HISTORY-{index:03d}-7f2b"
            source_ref = f"conversation:blind-history-{index:03d}"
            history.append(
                store.create(
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
            )
        pending = store.create(
            subject="user",
            predicate="verbatim_user_statement",
            value="W02-BLIND-PENDING-c2a9",
            kind="note",
            sensitivity="private",
            source_type="user_explicit",
            source_ref="conversation:blind-pending",
            confidence=0.9,
            review_status="pending",
        )
    finally:
        store.close()
    return history, pending


root = Path(tempfile.mkdtemp(prefix="memory4-protected-blind-index-"))
path = root / "memory.db"
provider = TestAeadProvider()
codec = MemoryProtectionCodec(provider)
history, pending = seed(path)
base = MemoryProtectionMigrator(path, codec).migrate()
check(base.complete, "base protected-memory migration completes")

new_candidate = confirmed("W02-BLIND-NEW-AFTER-128-51d4", "conversation:blind-new")
new_plan = MemoryConsolidator().plan([new_candidate], [])
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "landed protected W02-B retains its safe >128 fail-closed bound",
        lambda: apply_protected_consolidation_plan(
            writer,
            new_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        MemoryConsolidationWriteError,
    )

lookup_key = b"K" * LOOKUP_KEY_BYTES
migrator = ProtectedMemoryVerbatimLookupMigrator(
    path,
    codec,
    key_factory=lambda size: lookup_key if size == LOOKUP_KEY_BYTES else b"",
)
first = migrator.migrate(batch_limit=50)
check(
    not first.complete and first.indexed_total == 50 and first.rows_remaining == 91,
    "blind-index migration stops after its first explicit 50-row batch",
)
second = migrator.migrate(batch_limit=50)
check(
    not second.complete and second.indexed_total == 100 and second.rows_remaining == 41,
    "blind-index migration resumes with the same protected key",
)
final = migrator.migrate(batch_limit=50)
check(
    final.complete and final.indexed_total == 141 and final.rows_remaining == 0,
    "blind-index migration completes the >128 active canonical set",
)

ids = sidecar_ids(path)
check(len(ids) == 141 and pending.id in ids, "sidecar exactly covers active eligible rows")
check(
    sidecar_digest(path, history[0].id)
    != hashlib.sha256(history[0].value.encode()).hexdigest(),
    "sidecar does not store an unkeyed plaintext digest",
)
raw = family_bytes(path)
check(
    lookup_key not in raw
    and history[0].value.encode() not in raw
    and pending.value.encode() not in raw,
    "SQLite family contains neither raw lookup key nor sampled verbatim plaintext",
)

with ProtectedMemoryWriter(path, codec) as writer:
    created = apply_protected_consolidation_plan_indexed(
        writer,
        new_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(created.created_count == 1, "indexed W02 creates beyond 128 protected history rows")
new_id = created.created_ids[0]
check(new_id in sidecar_ids(path), "indexed create adds its blind-index row atomically")

with ProtectedMemoryWriter(path, codec) as writer:
    replay = apply_protected_consolidation_plan_indexed(
        writer,
        new_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    replay.replayed and replay.deduped_ids == (new_id,),
    "indexed W02 exact replay remains idempotent",
)

with ProtectedMemoryReader(path, codec) as reader:
    oldest = reader.get(history[0].id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
dedupe_candidate = confirmed(oldest.value, "conversation:blind-oldest-dedupe")
dedupe_plan = MemoryConsolidator().plan([dedupe_candidate], [oldest])
with ProtectedMemoryWriter(path, codec) as writer:
    deduped = apply_protected_consolidation_plan_indexed(
        writer,
        dedupe_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    deduped.deduped_ids == (oldest.id,) and deduped.created_count == 0,
    "blind selector finds an old exact value without decrypting unrelated history",
)

with ProtectedMemoryReader(path, codec) as reader:
    pending_record = reader.get(pending.id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
promotion_candidate = confirmed(pending_record.value, "conversation:blind-promotion")
promotion_plan = MemoryConsolidator().plan([promotion_candidate], [pending_record])
with ProtectedMemoryWriter(path, codec) as writer:
    promoted = apply_protected_consolidation_plan_indexed(
        writer,
        promotion_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
check(
    promoted.superseded_ids == (pending.id,) and len(promoted.superseding_ids) == 1,
    "indexed W02 preserves exact pending-to-confirmed version promotion",
)
promoted_id = promoted.superseding_ids[0]
ids = sidecar_ids(path)
check(
    pending.id not in ids and promoted_id in ids,
    "supersede removes predecessor fingerprint in the same transaction",
)

# Generic management delete intentionally does not know about the optional sidecar.
# That must produce fail-closed drift rather than leave a silently trusted fingerprint.
with ProtectedMemoryReader(path, codec) as reader:
    delete_target = reader.get(history[1].id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
with ProtectedMemoryWriter(path, codec) as writer:
    writer.delete(
        delete_target.id,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        expected_updated_at=delete_target.updated_at,
    )
check(delete_target.id in sidecar_ids(path), "generic delete leaves detectable sidecar drift")
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "stale extra fingerprint fails indexed W02 closed",
        lambda: apply_protected_consolidation_plan_indexed(
            writer,
            MemoryConsolidator().plan(
                [confirmed("W02-BLIND-AFTER-DELETE-82ce", "conversation:after-delete")],
                [],
            ),
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        IndexedMemoryConsolidationWriteError,
        "stale or incomplete",
    )
repair_delete = migrator.migrate(batch_limit=1)
check(repair_delete.complete, "one-row repair migration prunes stale deleted fingerprint")
check(delete_target.id not in sidecar_ids(path), "deleted content-derived fingerprint is removed")

# Generic canonical create produces the opposite drift: a missing fingerprint.
with ProtectedMemoryWriter(path, codec) as writer:
    unmanaged = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="user",
        predicate="verbatim_user_statement",
        value="W02-BLIND-OUT-OF-BAND-11a7",
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="management:out-of-band",
        confidence=1.0,
        review_status="confirmed",
    )
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "missing out-of-band fingerprint fails indexed W02 closed",
        lambda: apply_protected_consolidation_plan_indexed(
            writer,
            MemoryConsolidator().plan(
                [confirmed("W02-BLIND-AFTER-OOB-9e12", "conversation:after-oob")],
                [],
            ),
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        IndexedMemoryConsolidationWriteError,
        "stale or incomplete",
    )
repair_create = migrator.migrate(batch_limit=1)
check(repair_create.complete and unmanaged.id in sidecar_ids(path), "repair indexes missing active row")

# A late blind-index failure occurs after protected memory insertion but must roll
# the whole BEGIN IMMEDIATE transaction back.
rollback_plan = MemoryConsolidator().plan(
    [confirmed("W02-BLIND-ROLLBACK-35c1", "conversation:blind-rollback")],
    [],
)
before_memories = memory_count(path)
before_index = sidecar_ids(path)
original_index_created = ProtectedMemoryVerbatimLookup.index_created_locked


def fail_index_created(self, *args, **kwargs):
    raise ProtectedMemoryLookupError("injected blind-index failure")


ProtectedMemoryVerbatimLookup.index_created_locked = fail_index_created
try:
    with ProtectedMemoryWriter(path, codec) as writer:
        expect_error(
            "late blind-index failure propagates from indexed W02",
            lambda: apply_protected_consolidation_plan_indexed(
                writer,
                rollback_plan,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            ),
            IndexedMemoryConsolidationWriteError,
            "injected blind-index failure",
        )
finally:
    ProtectedMemoryVerbatimLookup.index_created_locked = original_index_created
check(
    memory_count(path) == before_memories and sidecar_ids(path) == before_index,
    "late blind-index failure rolls back memory and sidecar atomically",
)

# A tampered selector cannot use plan-supplied verbatim existing_id as a bypass.
conn = sqlite3.connect(path)
try:
    conn.execute(
        "UPDATE agent_memory_protected_verbatim_lookup SET value_hmac=? WHERE memory_id=?",
        ("0" * 64, history[2].id),
    )
    conn.commit()
finally:
    conn.close()
with ProtectedMemoryReader(path, codec) as reader:
    tampered_record = reader.get(history[2].id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
tampered_plan = MemoryConsolidator().plan(
    [confirmed(tampered_record.value, "conversation:blind-tamper")],
    [tampered_record],
)
with ProtectedMemoryWriter(path, codec) as writer:
    expect_error(
        "tampered selector cannot satisfy a trusted verbatim dedupe plan",
        lambda: apply_protected_consolidation_plan_indexed(
            writer,
            tampered_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        IndexedMemoryConsolidationWriteError,
        "stale or forged",
    )

print(f"\n===== W02 PROTECTED BLIND INDEX: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
