#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import sqlite3
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore, MemoryStoreError  # noqa: E402
from app.agent3.memory_consolidation import (  # noqa: E402
    MemoryConsolidationApplyError,
    apply_legacy_consolidation_plan,
    apply_protected_consolidation_plan,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
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
from app.memory import MemoryCandidate, MemoryConsolidator  # noqa: E402
from app.memory.extraction import (  # noqa: E402
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
)


class TestAeadProvider:
    provider_id = "memory4-w02b-test-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(
        self,
        key: bytes = b"memory4-w02b-test-key-not-production",
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
            raise MemoryProtectionError("W02-B ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("W02-B ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


passed = failed = 0


def check(condition: object, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_apply_error(name: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except MemoryConsolidationApplyError as exc:
        check(contains is None or contains in str(exc), name)
    except Exception:
        check(False, name)
    else:
        check(False, name)


def confirmed_statement(
    text: str,
    *,
    source_ref: str,
) -> MemoryCandidate:
    return MemoryCandidate(
        subject=VERBATIM_USER_SUBJECT,
        predicate=VERBATIM_USER_PREDICATE,
        value=text,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=text,
    )


def pending_candidate(
    predicate: str,
    value: str,
    *,
    source_ref: str,
) -> MemoryCandidate:
    return MemoryCandidate(
        subject="w02b",
        predicate=predicate,
        value=value,
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        source_ref=source_ref,
        confidence=0.6,
        review_status="pending",
        evidence="",
    )


def secret_candidate() -> MemoryCandidate:
    return MemoryCandidate(
        subject="w02b",
        predicate="secret",
        value="sk-w02b-secret-must-not-persist",
        kind="note",
        sensitivity="secret",
        source_type="inferred",
        source_ref="conversation:w02b-secret",
        confidence=0.5,
        review_status="pending",
        evidence="",
    )


def count_rows(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        conn.close()


def seed_and_migrate(path: Path) -> None:
    store = MemoryStore(str(path))
    try:
        store.create(
            subject="fixture",
            predicate="seed",
            value="seed-private-value",
            sensitivity="private",
        )
    finally:
        store.close()
    result = MemoryProtectionMigrator(
        path,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(result.complete, "W02-B protected fixture migration completes")


consolidator = MemoryConsolidator()

# Legacy path: multi-create is one transaction, replay is dedupe-only, stale plans
# fail before mutation, secrets never persist, and supersede remains review-only.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-w02b-legacy-") as raw:
    db = Path(raw) / "memory.db"
    store = MemoryStore(str(db))
    first = confirmed_statement(
        "I live in Copenhagen",
        source_ref="conversation:w02b-first",
    )
    second = confirmed_statement(
        "My workstation has 96 GB RAM",
        source_ref="conversation:w02b-second",
    )
    create_plan = consolidator.plan([first, second], [])
    receipt = apply_legacy_consolidation_plan(store, create_plan)
    check(
        receipt.committed
        and receipt.created_count == 2
        and receipt.reused_count == 0
        and len(receipt.created_ids) == 2,
        "W02-B legacy multi-create commits one bounded receipt",
    )
    check(
        {store.get(memory_id).value for memory_id in receipt.created_ids}
        == {first.value, second.value},
        "W02-B legacy create preserves exact candidate values",
    )

    replay_plan = consolidator.plan(
        [first, second],
        store.list(include_expired=True, include_secret=False, limit=128),
    )
    replay_before = len(store.list(include_expired=True, include_secret=True, limit=500))
    replay_receipt = apply_legacy_consolidation_plan(store, replay_plan)
    replay_after = len(store.list(include_expired=True, include_secret=True, limit=500))
    check(
        replay_receipt.created_count == 0
        and replay_receipt.reused_count == 2
        and replay_before == replay_after,
        "W02-B replay is idempotent after re-planning",
    )

    stale_candidate = pending_candidate(
        "stale-create",
        "planned",
        source_ref="run:w02b-stale",
    )
    stale_plan = consolidator.plan([stale_candidate], [])
    concurrent = store.create(**stale_candidate.store_fields())
    before_stale_apply = len(
        store.list(include_expired=True, include_secret=True, limit=500)
    )
    expect_apply_error(
        "W02-B stale legacy plan fails inside the write transaction",
        lambda: apply_legacy_consolidation_plan(store, stale_plan),
        "stale",
    )
    check(
        len(store.list(include_expired=True, include_secret=True, limit=500))
        == before_stale_apply
        and store.get(concurrent.id).value == "planned",
        "W02-B stale legacy refusal leaves durable state unchanged",
    )

    hidden = secret_candidate()
    secret_plan = consolidator.plan([hidden], [])
    secret_before = len(store.list(include_expired=True, include_secret=True, limit=500))
    secret_receipt = apply_legacy_consolidation_plan(store, secret_plan)
    secret_after = len(store.list(include_expired=True, include_secret=True, limit=500))
    check(
        secret_receipt.skipped_count == 1
        and secret_receipt.created_count == 0
        and secret_before == secret_after,
        "W02-B never auto-persists secret candidates to legacy plaintext storage",
    )

    pending_verbatim = store.create(
        subject=VERBATIM_USER_SUBJECT,
        predicate=VERBATIM_USER_PREDICATE,
        value="I use ModelRig every day",
        kind="note",
        sensitivity="private",
        source_type="inferred",
        source_ref="run:w02b-pending-verbatim",
        confidence=0.4,
        review_status="pending",
    )
    promoted = confirmed_statement(
        "I use ModelRig every day",
        source_ref="conversation:w02b-promoted",
    )
    promotion_plan = consolidator.plan([promoted], [pending_verbatim])
    promotion_receipt = apply_legacy_consolidation_plan(store, promotion_plan)
    check(
        promotion_receipt.review_count == 1
        and promotion_receipt.review_existing_ids == (pending_verbatim.id,)
        and store.get(pending_verbatim.id).review_status == "pending"
        and store.get(pending_verbatim.id).lifecycle_status == "active",
        "W02-B treats W02-A supersede as non-mutating local review handoff",
    )

    forged_action = replace(create_plan.actions[0], reason="forged-write-authority")
    forged_plan = replace(
        create_plan,
        actions=(forged_action,) + create_plan.actions[1:],
    )
    forged_before = len(store.list(include_expired=True, include_secret=True, limit=500))
    expect_apply_error(
        "W02-B rejects a forged plan even when candidate objects are valid",
        lambda: apply_legacy_consolidation_plan(store, forged_plan),
        "stale",
    )
    check(
        len(store.list(include_expired=True, include_secret=True, limit=500))
        == forged_before,
        "W02-B forged plan rejection performs no legacy write",
    )

    rollback_a = pending_candidate(
        "rollback-a",
        "A",
        source_ref="run:w02b-rollback-a",
    )
    rollback_b = pending_candidate(
        "rollback-b",
        "B",
        source_ref="run:w02b-rollback-b",
    )
    rollback_plan = consolidator.plan([rollback_a, rollback_b], [])
    rollback_before = len(store.list(include_expired=True, include_secret=True, limit=500))
    original_insert = store._insert_locked
    insert_calls = 0

    def fail_second_insert(**fields):
        nonlocal_marker = None
        del nonlocal_marker
        global_marker = None
        del global_marker
        # The mutable list avoids introducing test-only hooks in production code.
        insert_counter[0] += 1
        if insert_counter[0] == 2:
            raise MemoryStoreError("injected second W02-B legacy insert failure")
        return original_insert(**fields)

    insert_counter = [0]
    store._insert_locked = fail_second_insert  # type: ignore[method-assign]
    expect_apply_error(
        "W02-B late legacy insert failure aborts the whole batch",
        lambda: apply_legacy_consolidation_plan(store, rollback_plan),
        "failed closed",
    )
    store._insert_locked = original_insert  # type: ignore[method-assign]
    check(
        len(store.list(include_expired=True, include_secret=True, limit=500))
        == rollback_before,
        "W02-B legacy transaction leaves no first-row partial commit",
    )

    safe_receipt_json = json.dumps(receipt.to_dict())
    check(
        first.value not in safe_receipt_json
        and first.source_ref not in safe_receipt_json
        and second.value not in safe_receipt_json,
        "W02-B durable receipt exposes ids/counts but no values or provenance text",
    )
    store.close()


# Protected path: the same contract is enforced under LOCAL_MANAGEMENT, but every
# new private value/source_ref is encrypted and a late crypto failure rolls back
# earlier rows from the same W02-B batch.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-w02b-protected-") as raw:
    db = Path(raw) / "memory.db"
    seed_and_migrate(db)
    ids = iter(("w02b-protected-001", "w02b-protected-002", "w02b-unused-003"))
    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: next(ids),
        clock=itertools.count(10_000).__next__,
    )
    protected_first = confirmed_statement(
        "My protected first W02-B note",
        source_ref="conversation:w02b-protected-first",
    )
    protected_second = confirmed_statement(
        "My protected second W02-B note",
        source_ref="conversation:w02b-protected-second",
    )
    protected_plan = consolidator.plan([protected_first, protected_second], [])
    protected_receipt = apply_protected_consolidation_plan(
        writer,
        protected_plan,
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
    )
    check(
        protected_receipt.committed
        and protected_receipt.created_count == 2
        and protected_receipt.reused_count == 0,
        "W02-B protected multi-create commits atomically",
    )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        protected_rows = conn.execute(
            "SELECT id,value,source_ref,value_protected,source_ref_protected "
            "FROM agent_memories WHERE id IN (?,?) ORDER BY id",
            protected_receipt.created_ids,
        ).fetchall()
    finally:
        conn.close()
    check(
        len(protected_rows) == 2
        and all(row["value"] == "" and row["source_ref"] is None for row in protected_rows)
        and all(row["value_protected"] and row["source_ref_protected"] for row in protected_rows),
        "W02-B protected batch writes no sensitive plaintext columns",
    )

    with ProtectedMemoryReader(db, MemoryProtectionCodec(TestAeadProvider())) as reader:
        opened = {
            reader.get(memory_id, access=MemoryReadAccess.LOCAL_MANAGEMENT).value
            for memory_id in protected_receipt.created_ids
        }
    check(
        opened == {protected_first.value, protected_second.value},
        "W02-B protected batch remains readable through local-management authority",
    )

    expect_apply_error(
        "W02-B protected persistence requires exact LOCAL_MANAGEMENT authority",
        lambda: apply_protected_consolidation_plan(
            writer,
            consolidator.plan(
                [
                    pending_candidate(
                        "bad-access",
                        "no-write",
                        source_ref="run:w02b-bad-access",
                    )
                ],
                [],
            ),
            access="local_management",  # type: ignore[arg-type]
        ),
        "failed closed",
    )
    writer.close()


with tempfile.TemporaryDirectory(prefix="kaliv-memory4-w02b-protected-rollback-") as raw:
    db = Path(raw) / "memory.db"
    seed_and_migrate(db)
    before = count_rows(db)
    failing_writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider(fail_on_protect_call=3)),
        id_factory=iter(("w02b-fail-001", "w02b-fail-002")).__next__,
        clock=itertools.count(20_000).__next__,
    )
    fail_a = confirmed_statement(
        "W02-B encrypted rollback statement A",
        source_ref="conversation:w02b-fail-a",
    )
    fail_b = confirmed_statement(
        "W02-B encrypted rollback statement B",
        source_ref="conversation:w02b-fail-b",
    )
    fail_plan = consolidator.plan([fail_a, fail_b], [])
    expect_apply_error(
        "W02-B late protected encryption failure aborts the whole batch",
        lambda: apply_protected_consolidation_plan(
            failing_writer,
            fail_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
        "failed closed",
    )
    failing_writer.close()
    check(
        count_rows(db) == before,
        "W02-B protected transaction leaves no first-row partial commit",
    )


print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
