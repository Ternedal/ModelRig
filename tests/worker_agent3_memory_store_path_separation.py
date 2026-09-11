#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore, MemoryStoreError  # noqa: E402
from app.agent3.memory_consolidation_writer import (  # noqa: E402
    MemoryConsolidationWriteError,
    apply_legacy_consolidation_plan,
    apply_protected_consolidation_plan,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
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
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402
from app.agent3.memory_surface import mount_memory_surface  # noqa: E402
from app.memory import (  # noqa: E402
    ConsolidationAction,
    ConsolidationPlan,
    ConsolidationReceipt,
    MemoryCandidate,
    MemoryConsolidator,
)

checks: list[tuple[str, bool]] = []
SIGNING_MATERIAL = hashlib.sha256(
    b"t033-store-path-separation-fixture"
).hexdigest()


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


@contextmanager
def environment(**values: str):
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class MustNotBeConstructed:
    def __init__(self) -> None:
        raise AssertionError("provider must not be constructed before path validation")


class TestAeadProvider:
    provider_id = "test-w02b-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(
        self,
        key: bytes = b"w02b-test-key-not-production",
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


def pending_candidate(
    *,
    subject: str,
    predicate: str,
    value: str,
    source_ref: str,
) -> MemoryCandidate:
    return MemoryCandidate(
        subject=subject,
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


def confirmed_statement(text: str, source_ref: str) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=text,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=text,
    )


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


with tempfile.TemporaryDirectory(prefix="kaliv-t033-path-separation-") as raw:
    shared = Path(raw) / "shared.db"
    with environment(
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_API_SECRET=SIGNING_MATERIAL,
        KALIV_AGENT3_MEMORY_GRANT_DB=str(shared),
    ):
        try:
            mount_memory_surface(
                FastAPI(),
                memory_path=shared,
                grant_db_path=shared,
                protected_provider_factory=MustNotBeConstructed,
            )
        except RuntimeError as exc:
            check(
                "shared memory and replay-ledger path fails closed",
                "separate" in str(exc),
            )
        else:
            check("shared memory and replay-ledger path fails closed", False)
        check(
            "shared path failure happens before database/provider creation",
            not shared.exists(),
        )


# Memory 4.0 W02-B: execute a W02-A plan only after a fresh in-transaction
# replan. The adapter deliberately uses storage internals already protected by
# BEGIN IMMEDIATE so a multi-action batch is all-or-nothing.
with tempfile.TemporaryDirectory(prefix="kaliv-w02b-legacy-") as raw:
    path = Path(raw) / "memory.db"
    store = MemoryStore(str(path))
    consolidator = MemoryConsolidator()

    first = pending_candidate(
        subject="modelrig",
        predicate="writer_candidate",
        value="qwen",
        source_ref="run:w02b-create",
    )
    create_plan = consolidator.plan([first], [])
    receipt = apply_legacy_consolidation_plan(store, create_plan)
    created = store.get(receipt.created_ids[0])
    check(
        "W02-B legacy create preserves candidate authority fields exactly",
        receipt.created_count == 1
        and created.kind == first.kind
        and created.sensitivity == first.sensitivity
        and created.source_type == first.source_type
        and created.source_ref == first.source_ref
        and created.confidence == first.confidence
        and created.review_status == first.review_status,
    )
    replay = apply_legacy_consolidation_plan(store, create_plan)
    check(
        "W02-B exact legacy replay is a no-op bound to the full durable row",
        replay.replayed
        and replay.created_count == 0
        and replay.deduped_ids == (created.id,)
        and len(store.list(subject="modelrig", predicate="writer_candidate")) == 1,
    )

    stale_candidate = pending_candidate(
        subject="modelrig",
        predicate="stale_writer",
        value="same-value",
        source_ref="run:w02b-planned-source",
    )
    stale_plan = consolidator.plan([stale_candidate], store.list(limit=128))
    store.create(
        subject=stale_candidate.subject,
        predicate=stale_candidate.predicate,
        value=stale_candidate.value,
        kind=stale_candidate.kind,
        sensitivity=stale_candidate.sensitivity,
        source_type=stale_candidate.source_type,
        source_ref="run:w02b-different-source",
        confidence=stale_candidate.confidence,
        review_status=stale_candidate.review_status,
    )
    expect_error(
        "W02-B refuses stale create when an exact value appeared with different provenance",
        lambda: apply_legacy_consolidation_plan(store, stale_plan),
        MemoryConsolidationWriteError,
        "stale",
    )

    forged_candidate = pending_candidate(
        subject="modelrig",
        predicate="forged_writer",
        value="forged",
        source_ref="run:w02b-forged",
    )
    forged = ConsolidationPlan(
        actions=(
            ConsolidationAction(
                decision="skip",
                candidate=forged_candidate,
                existing_id=None,
                reason="secret_candidate",
            ),
        ),
        receipt=ConsolidationReceipt(
            considered_count=1,
            create_count=0,
            dedupe_count=0,
            supersede_count=0,
            skip_count=1,
            touched_existing_ids=(),
            sent_to_store=False,
        ),
    )
    expect_error(
        "W02-B rejects a forged plan even when its receipt is internally consistent",
        lambda: apply_legacy_consolidation_plan(store, forged),
        MemoryConsolidationWriteError,
        "not produced by W02-A",
    )

    promotion_text = "I live in Copenhagen"
    pending_old = store.create(
        subject="user",
        predicate="verbatim_user_statement",
        value=promotion_text,
        kind="note",
        sensitivity="private",
        source_type="inferred",
        source_ref="run:w02b-pending-verbatim",
        confidence=0.4,
        review_status="pending",
    )
    promoted_candidate = confirmed_statement(
        promotion_text,
        "conversation:w02b-confirmed-verbatim",
    )
    promotion_plan = consolidator.plan(
        [promoted_candidate],
        store.list(include_expired=True, limit=128),
    )
    promotion_receipt = apply_legacy_consolidation_plan(store, promotion_plan)
    promoted = store.get(promotion_receipt.superseding_ids[0])
    old_after = store.get(pending_old.id)
    check(
        "W02-B legacy supersede is version-preserving and keeps candidate provenance",
        promotion_receipt.superseded_ids == (pending_old.id,)
        and old_after.lifecycle_status == "superseded"
        and promoted.supersedes_id == pending_old.id
        and promoted.source_type == promoted_candidate.source_type
        and promoted.source_ref == promoted_candidate.source_ref
        and promoted.review_status == "confirmed",
    )
    promotion_replay = apply_legacy_consolidation_plan(store, promotion_plan)
    check(
        "W02-B supersede replay is idempotent only through the exact replacement link",
        promotion_replay.replayed
        and promotion_replay.deduped_ids == (promoted.id,)
        and len(store.history("user", "verbatim_user_statement")) >= 2,
    )

    rollback_a = pending_candidate(
        subject="rollback",
        predicate="a",
        value="one",
        source_ref="run:w02b-rollback-a",
    )
    rollback_b = pending_candidate(
        subject="rollback",
        predicate="b",
        value="two",
        source_ref="run:w02b-rollback-b",
    )
    rollback_plan = consolidator.plan(
        [rollback_a, rollback_b],
        store.list(include_expired=True, limit=128),
    )
    before = len(store.list(include_expired=True, include_secret=True, limit=500))
    original_insert = store._insert_locked
    insert_calls = [0]

    def fail_second_insert(**kwargs):
        insert_calls[0] += 1
        if insert_calls[0] == 2:
            raise MemoryStoreError("injected W02-B legacy batch failure")
        return original_insert(**kwargs)

    store._insert_locked = fail_second_insert  # type: ignore[method-assign]
    try:
        expect_error(
            "W02-B legacy batch surfaces a late mutation failure",
            lambda: apply_legacy_consolidation_plan(store, rollback_plan),
            MemoryStoreError,
            "injected",
        )
    finally:
        store._insert_locked = original_insert  # type: ignore[method-assign]
    after = len(store.list(include_expired=True, include_secret=True, limit=500))
    check(
        "W02-B legacy batch rollback removes earlier writes from the failed transaction",
        before == after
        and not store.list(subject="rollback", predicate="a", include_expired=True)
        and not store.list(subject="rollback", predicate="b", include_expired=True),
    )
    store.close()


with tempfile.TemporaryDirectory(prefix="kaliv-w02b-protected-") as raw:
    path = Path(raw) / "memory.db"
    provider = TestAeadProvider()
    legacy = MemoryStore(str(path))
    protected_pending = legacy.create(
        subject="user",
        predicate="verbatim_user_statement",
        value="I use ModelRig locally",
        kind="note",
        sensitivity="private",
        source_type="inferred",
        source_ref="run:w02b-protected-pending",
        confidence=0.5,
        review_status="pending",
    )
    legacy.close()
    summary = MemoryProtectionMigrator(
        path,
        MemoryProtectionCodec(provider),
    ).migrate()
    check("W02-B protected fixture migration completes", summary.complete)

    codec = MemoryProtectionCodec(provider)
    with ProtectedMemoryWriter(path, codec) as writer:
        with ProtectedMemoryReader(path, codec) as reader:
            snapshot = reader.list(
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
                lifecycle_status="active",
                include_expired=True,
                limit=128,
            )
        protected_candidate = confirmed_statement(
            "I use ModelRig locally",
            "conversation:w02b-protected-confirmed",
        )
        protected_plan = MemoryConsolidator().plan([protected_candidate], snapshot)
        protected_receipt = apply_protected_consolidation_plan(
            writer,
            protected_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
        with ProtectedMemoryReader(path, codec) as reader:
            replacement = reader.get(
                protected_receipt.superseding_ids[0],
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
            )
            old = reader.get(
                protected_pending.id,
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
            )
        check(
            "W02-B protected supersede preserves version/provenance through encrypted storage",
            old.lifecycle_status == "superseded"
            and replacement.supersedes_id == protected_pending.id
            and replacement.value == protected_candidate.value
            and replacement.source_ref == protected_candidate.source_ref
            and replacement.source_type == protected_candidate.source_type
            and replacement.review_status == protected_candidate.review_status,
        )
        raw_row = sqlite3.connect(path).execute(
            "SELECT value,source_ref,value_protected,source_ref_protected "
            "FROM agent_memories WHERE id=?",
            (replacement.id,),
        ).fetchone()
        check(
            "W02-B protected rows keep value/source_ref out of plaintext columns",
            raw_row is not None
            and raw_row[0] == ""
            and raw_row[1] is None
            and raw_row[2]
            and raw_row[3]
            and protected_candidate.value.encode("utf-8") not in family_bytes(path)
            and protected_candidate.source_ref.encode("utf-8") not in family_bytes(path),
        )
        protected_replay = apply_protected_consolidation_plan(
            writer,
            protected_plan,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        )
        check(
            "W02-B protected exact replay is a no-op bound to the replacement row",
            protected_replay.replayed
            and protected_replay.deduped_ids == (replacement.id,),
        )
        expect_error(
            "W02-B protected writes require the exact local-management authority token",
            lambda: apply_protected_consolidation_plan(
                writer,
                protected_plan,
                access="local_management",  # type: ignore[arg-type]
            ),
            ProtectedMemoryWriteError,
            "local_management",
        )

    rollback_provider = TestAeadProvider()
    rollback_path = Path(raw) / "rollback.db"
    seed = MemoryStore(str(rollback_path))
    seed.close()
    migration = MemoryProtectionMigrator(
        rollback_path,
        MemoryProtectionCodec(rollback_provider),
    ).migrate()
    check("W02-B protected rollback fixture migration completes", migration.complete)
    rollback_provider.calls = 0
    rollback_provider.fail_on_protect_call = 3
    rollback_codec = MemoryProtectionCodec(rollback_provider)
    rollback_one = pending_candidate(
        subject="protected-rollback",
        predicate="a",
        value="first-sensitive-value",
        source_ref="run:protected-rollback-a",
    )
    rollback_two = pending_candidate(
        subject="protected-rollback",
        predicate="b",
        value="second-sensitive-value",
        source_ref="run:protected-rollback-b",
    )
    rollback_plan = MemoryConsolidator().plan([rollback_one, rollback_two], [])
    before_count = sqlite3.connect(rollback_path).execute(
        "SELECT COUNT(*) FROM agent_memories"
    ).fetchone()[0]
    with ProtectedMemoryWriter(rollback_path, rollback_codec) as writer:
        expect_error(
            "W02-B protected batch surfaces an injected second-action encryption failure",
            lambda: apply_protected_consolidation_plan(
                writer,
                rollback_plan,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
            ),
            ProtectedMemoryWriteError,
            "encrypted",
        )
    after_count = sqlite3.connect(rollback_path).execute(
        "SELECT COUNT(*) FROM agent_memories"
    ).fetchone()[0]
    check(
        "W02-B protected late encryption failure rolls the whole mutating batch back",
        before_count == after_count
        and rollback_one.value.encode("utf-8") not in family_bytes(rollback_path)
        and rollback_two.value.encode("utf-8") not in family_bytes(rollback_path),
    )


failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 STORE PATH + W02-B: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
