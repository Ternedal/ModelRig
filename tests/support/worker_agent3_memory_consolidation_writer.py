from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryConflict, MemoryStore
from app.agent3.memory_consolidation_writer import (
    WRITE_RECEIPT_SCHEMA,
    MemoryConsolidationWriteError,
    apply_legacy_consolidation_plan,
    apply_protected_consolidation_plan,
)
from app.agent3.memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from app.agent3.memory_protected_writer import (
    MemoryWriteAccess,
    ProtectedMemoryWriteError,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import (
    ConsolidationPlan,
    ConsolidationReceipt,
    MemoryCandidate,
    MemoryConsolidator,
)


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


def pending_candidate(
    value: str,
    *,
    subject: str = "anders",
    predicate: str = "project_status",
    source_ref: str = "conversation:w02b-pending",
) -> MemoryCandidate:
    return MemoryCandidate(
        subject=subject,
        predicate=predicate,
        value=value,
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        source_ref=source_ref,
        confidence=0.8,
        review_status="pending",
        evidence="",
    )


def confirmed_verbatim(
    value: str,
    *,
    source_ref: str = "conversation:w02b-confirmed",
) -> MemoryCandidate:
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


# --- Legacy writer: create, dedupe, exact replay, bounded lookup and stale refusal.
legacy_path = os.path.join(tempfile.mkdtemp(prefix="w02b-legacy-"), "memory.db")
legacy = MemoryStore(legacy_path)

# More than the global W02-A snapshot bound must not brick unrelated writes.
for index in range(140):
    legacy.create(
        subject=f"unrelated-{index}",
        predicate="noise",
        value=f"noise-{index}",
        sensitivity="private",
        source_type="inferred",
        source_ref=f"seed:{index}",
    )

candidate_a = pending_candidate("shipping", source_ref="conversation:w02b-a")
create_plan = plan([candidate_a])
created_receipt = apply_legacy_consolidation_plan(legacy, create_plan)
check(
    created_receipt.schema == WRITE_RECEIPT_SCHEMA
    and created_receipt.created_count == 1
    and created_receipt.deduped_count == 0
    and created_receipt.replayed is False
    and created_receipt.sent_to_store is True,
    "legacy W02-B creates against a large store using only relevant bounded rows",
)
created_id = created_receipt.created_ids[0]
created = legacy.get(created_id)
check(
    created.subject == candidate_a.subject
    and created.predicate == candidate_a.predicate
    and created.value == candidate_a.value
    and created.kind == candidate_a.kind
    and created.sensitivity == candidate_a.sensitivity
    and created.source_type == candidate_a.source_type
    and created.source_ref == candidate_a.source_ref
    and created.confidence == candidate_a.confidence
    and created.review_status == candidate_a.review_status,
    "legacy W02-B preserves candidate provenance/review/privacy fields exactly",
)

dedupe_plan = plan([candidate_a], [created])
dedupe_receipt = apply_legacy_consolidation_plan(legacy, dedupe_plan)
check(
    dedupe_receipt.created_count == 0
    and dedupe_receipt.deduped_ids == (created_id,)
    and dedupe_receipt.replayed is False,
    "legacy W02-B applies a current dedupe plan without mutation",
)

replay_receipt = apply_legacy_consolidation_plan(legacy, create_plan)
check(
    replay_receipt.replayed is True
    and replay_receipt.created_count == 0
    and replay_receipt.deduped_ids == (created_id,),
    "legacy W02-B exact create replay is an idempotent no-op",
)

stale_candidate = pending_candidate(
    "stale",
    predicate="stale_check",
    source_ref="conversation:w02b-stale",
)
stale_plan = plan([stale_candidate])
legacy.create(
    subject=stale_candidate.subject,
    predicate=stale_candidate.predicate,
    value=stale_candidate.value,
    kind=stale_candidate.kind,
    sensitivity=stale_candidate.sensitivity,
    source_type=stale_candidate.source_type,
    source_ref="different-source",
    confidence=stale_candidate.confidence,
    review_status=stale_candidate.review_status,
)
expect_error(
    "legacy W02-B refuses a stale create plan that is not an exact replay",
    lambda: apply_legacy_consolidation_plan(legacy, stale_plan),
    MemoryConsolidationWriteError,
)

forged = ConsolidationPlan(
    actions=create_plan.actions,
    receipt=ConsolidationReceipt(
        considered_count=99,
        create_count=1,
        dedupe_count=0,
        supersede_count=0,
        skip_count=0,
        touched_existing_ids=(),
        sent_to_store=False,
    ),
)
expect_error(
    "legacy W02-B rejects a forged plan receipt before mutation",
    lambda: apply_legacy_consolidation_plan(legacy, forged),
    MemoryConsolidationWriteError,
)

secret_candidate = MemoryCandidate(
    subject="user",
    predicate="credential",
    value="secret-material",
    kind="fact",
    sensitivity="secret",
    source_type="inferred",
    source_ref="conversation:w02b-secret",
    confidence=0.9,
    review_status="pending",
    evidence="",
)
secret_plan = plan([secret_candidate])
secret_receipt = apply_legacy_consolidation_plan(legacy, secret_plan)
check(
    secret_receipt.created_count == 0
    and secret_receipt.skipped_count == 1
    and not legacy.list(subject="user", predicate="credential", include_secret=True),
    "legacy W02-B never auto-persists a secret candidate",
)

# Exact pending -> confirmed verbatim authority promotion is versioned, never in-place.
promotion_value = "I live in Copenhagen"
pending_old = legacy.create(
    subject="user",
    predicate="verbatim_user_statement",
    value=promotion_value,
    kind="note",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:old-pending",
    confidence=0.5,
    review_status="pending",
)
promotion_candidate = confirmed_verbatim(
    promotion_value,
    source_ref="conversation:w02b-promotion",
)
promotion_plan = plan([promotion_candidate], [pending_old])
check(
    promotion_plan.actions[0].decision == "supersede"
    and promotion_plan.actions[0].existing_id == pending_old.id,
    "W02-A exposes only the exact verbatim authority promotion to W02-B",
)
promotion_receipt = apply_legacy_consolidation_plan(legacy, promotion_plan)
new_id = promotion_receipt.superseding_ids[0]
old_after = legacy.get(pending_old.id)
new_after = legacy.get(new_id)
check(
    old_after.lifecycle_status == "superseded"
    and new_after.lifecycle_status == "active"
    and new_after.supersedes_id == pending_old.id
    and new_after.source_type == "user_explicit"
    and new_after.source_ref == promotion_candidate.source_ref
    and new_after.review_status == "confirmed",
    "legacy W02-B versions exact authority promotion and preserves new provenance",
)
replayed_promotion = apply_legacy_consolidation_plan(legacy, promotion_plan)
check(
    replayed_promotion.replayed is True
    and replayed_promotion.deduped_ids == (new_id,),
    "legacy supersede replay resolves to the already-created version",
)

# A late failure must roll back every earlier create in the same plan.
rollback_a = pending_candidate(
    "rollback-a",
    subject="rollback",
    predicate="a",
    source_ref="conversation:rollback-a",
)
rollback_b = pending_candidate(
    "rollback-b",
    subject="rollback",
    predicate="b",
    source_ref="conversation:rollback-b",
)
rollback_plan = plan([rollback_a, rollback_b])
original_insert = legacy._insert_locked
insert_calls = 0


def fail_second_insert(**kwargs):
    global insert_calls
    insert_calls += 1
    if insert_calls == 2:
        raise MemoryConflict("injected second insert failure")
    return original_insert(**kwargs)


legacy._insert_locked = fail_second_insert
expect_error(
    "legacy W02-B propagates a late insert failure",
    lambda: apply_legacy_consolidation_plan(legacy, rollback_plan),
    MemoryConflict,
)
legacy._insert_locked = original_insert
check(
    not legacy.list(subject="rollback", predicate="a")
    and not legacy.list(subject="rollback", predicate="b"),
    "legacy W02-B rolls the full mutating batch back on late failure",
)

receipt_payload = created_receipt.to_dict()
receipt_text = repr(receipt_payload)
check(
    "value" not in receipt_payload
    and "evidence" not in receipt_payload
    and "source_ref" not in receipt_payload
    and candidate_a.value not in receipt_text
    and candidate_a.source_ref not in receipt_text,
    "W02-B receipt omits candidate values/evidence/source_ref",
)
legacy.close()


# --- Protected writer qualification.
class TestAeadProvider:
    provider_id = "test-w02b-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(
        self,
        key: bytes = b"w02b-protected-test-key",
        *,
        fail_on_protect_call: int | None = None,
    ):
        self.key = key
        self.calls = 0
        self.fail_on_protect_call = fail_on_protect_call

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
        if self.calls == self.fail_on_protect_call:
            raise MemoryProtectionError("injected W02-B protection failure")
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
            raise MemoryProtectionError("ciphertext truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


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


def row_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        connection.close()


protected_root = Path(tempfile.mkdtemp(prefix="w02b-protected-"))
protected_db = protected_root / "memory.db"
seed = MemoryStore(str(protected_db))
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
migration = MemoryProtectionMigrator(protected_db, base_codec).migrate()
check(migration.complete, "protected W02-B fixture migration completes")

id_values = iter(
    [
        "w02b-created-001",
        "w02b-pending-old-002",
        "w02b-promoted-003",
        "w02b-rollback-a-004",
        "w02b-rollback-b-005",
        "w02b-unused-006",
    ]
)
writer = ProtectedMemoryWriter(
    protected_db,
    MemoryProtectionCodec(TestAeadProvider()),
    id_factory=lambda: next(id_values),
)
protected_candidate = pending_candidate(
    "protected-new-value",
    subject="protected",
    predicate="new",
    source_ref="conversation:protected-new",
)
protected_plan = plan([protected_candidate])
protected_receipt = apply_protected_consolidation_plan(
    writer,
    protected_plan,
    access=MemoryWriteAccess.LOCAL_MANAGEMENT,
)
protected_id = protected_receipt.created_ids[0]
with ProtectedMemoryReader(
    protected_db,
    MemoryProtectionCodec(TestAeadProvider()),
) as protected_reader:
    protected_record = protected_reader.get(
        protected_id,
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
check(
    protected_record.value == protected_candidate.value
    and protected_record.source_ref == protected_candidate.source_ref
    and protected_record.review_status == "pending",
    "protected W02-B round-trips exact candidate fields through encrypted storage",
)
raw = sqlite3.connect(protected_db)
try:
    stored = raw.execute(
        "SELECT value,source_ref,protection_state FROM agent_memories WHERE id=?",
        (protected_id,),
    ).fetchone()
finally:
    raw.close()
protected_family = family_bytes(protected_db)
check(
    stored == ("", None, "protected")
    and protected_candidate.value.encode("utf-8") not in protected_family
    and protected_candidate.source_ref.encode("utf-8") not in protected_family,
    "protected W02-B keeps value/source_ref plaintext out of SQLite family files",
)

protected_replay = apply_protected_consolidation_plan(
    writer,
    protected_plan,
    access=MemoryWriteAccess.LOCAL_MANAGEMENT,
)
check(
    protected_replay.replayed is True
    and protected_replay.deduped_ids == (protected_id,),
    "protected W02-B create replay is idempotent",
)

expect_error(
    "protected W02-B requires exact LOCAL_MANAGEMENT authority",
    lambda: apply_protected_consolidation_plan(writer, protected_plan, access=None),
    ProtectedMemoryWriteError,
)

protected_promotion_value = "I use ModelRig"
protected_old = writer.create(
    access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    subject="user",
    predicate="verbatim_user_statement",
    value=protected_promotion_value,
    kind="note",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:protected-old",
    confidence=0.4,
    review_status="pending",
)
protected_promotion_candidate = confirmed_verbatim(
    protected_promotion_value,
    source_ref="conversation:protected-promotion",
)
protected_promotion_plan = plan([protected_promotion_candidate], [protected_old])
protected_promotion_receipt = apply_protected_consolidation_plan(
    writer,
    protected_promotion_plan,
    access=MemoryWriteAccess.LOCAL_MANAGEMENT,
)
protected_new_id = protected_promotion_receipt.superseding_ids[0]
with ProtectedMemoryReader(
    protected_db,
    MemoryProtectionCodec(TestAeadProvider()),
) as protected_reader:
    protected_old_after = protected_reader.get(
        protected_old.id,
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
    protected_new_after = protected_reader.get(
        protected_new_id,
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
check(
    protected_old_after.lifecycle_status == "superseded"
    and protected_new_after.supersedes_id == protected_old.id
    and protected_new_after.review_status == "confirmed"
    and protected_new_after.source_ref == protected_promotion_candidate.source_ref,
    "protected W02-B versions exact authority promotion without overwriting history",
)
writer.close()

# Failure on the second candidate's value encryption must roll back the first insert.
rollback_writer = ProtectedMemoryWriter(
    protected_db,
    MemoryProtectionCodec(TestAeadProvider(fail_on_protect_call=3)),
    id_factory=lambda: next(id_values),
)
protected_rollback_a = pending_candidate(
    "protected-rollback-a",
    subject="protected-rollback",
    predicate="a",
    source_ref="conversation:protected-rollback-a",
)
protected_rollback_b = pending_candidate(
    "protected-rollback-b",
    subject="protected-rollback",
    predicate="b",
    source_ref="conversation:protected-rollback-b",
)
protected_rollback_plan = plan([protected_rollback_a, protected_rollback_b])
before_rows = row_count(protected_db)
expect_error(
    "protected W02-B propagates a late encryption failure",
    lambda: apply_protected_consolidation_plan(
        rollback_writer,
        protected_rollback_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    ),
    ProtectedMemoryWriteError,
)
rollback_family = family_bytes(protected_db)
check(
    row_count(protected_db) == before_rows
    and protected_rollback_a.value.encode("utf-8") not in rollback_family
    and protected_rollback_b.value.encode("utf-8") not in rollback_family,
    "protected W02-B rolls back the whole batch and leaves no sensitive plaintext",
)
rollback_writer.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
