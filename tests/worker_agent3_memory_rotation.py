#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import tempfile

from app.agent3.memory import MemoryStore, MemoryStoreError
from app.agent3.memory_protection import PREFIX, parse_envelope
from helpers.memory_protector import TestMemoryProtector

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejects(fn, message: str) -> None:
    try:
        fn()
    except MemoryStoreError:
        check(True, message)
    else:
        check(False, message)


def raw_rows(path: str):
    with sqlite3.connect(path) as db:
        return db.execute(
            "SELECT id,value,source_ref FROM agent_memories "
            "WHERE sensitivity IN ('private','secret') ORDER BY id"
        ).fetchall()


def metadata(path: str) -> dict[str, str]:
    with sqlite3.connect(path) as db:
        return dict(db.execute("SELECT key,value FROM agent_memory_meta").fetchall())


root = tempfile.mkdtemp(prefix="agent3-memory-rotation-")
path = os.path.join(root, "memory.db")
old = TestMemoryProtector(key=b"rotation-old-key", key_id="old-key")
new = TestMemoryProtector(key=b"rotation-new-key", key_id="new-key")
store = MemoryStore(path, protector=old)
private = store.create(
    subject="anders",
    predicate="rotation-private",
    value="rotation-private-value",
    sensitivity="private",
    source_ref="rotation:private-source",
)
secret = store.create(
    subject="anders",
    predicate="rotation-secret",
    value="rotation-secret-value",
    sensitivity="secret",
    source_ref="rotation:secret-source",
)
public = store.create(
    subject="modelrig",
    predicate="rotation-public",
    value="public-unchanged",
    sensitivity="public",
)
old_scope = metadata(path)["store_scope"]
old_rows = raw_rows(path)
old_serialized = "\n".join(str(value) for row in old_rows for value in row[1:] if value)

result = store.rotate_protection(new)
check(result["rotated_records"] == 2, "key rotation rewrites every live sensitive record")
check(result["old_store_scope"] == old_scope == result["new_store_scope"], "key rotation preserves scope by default")
check(result["provider"] == new.provider and result["key_id"] == "new-key", "rotation reports new provider identity")
check(result["generation"] == 1 and not result["no_op"], "first rotation records generation one")
check(not result["compaction_pending"], "successful rotation compacts old ciphertext immediately")
check(store.get(private.id).value == "rotation-private-value", "live store reads private value with new protector")
check(store.get(secret.id, include_deleted=True).value == "rotation-secret-value", "live store reads secret value with new protector")
check(store.get(public.id).value == "public-unchanged", "public row is not rewritten by protection rotation")

rotated_rows = raw_rows(path)
check(rotated_rows != old_rows, "stored sensitive envelopes changed during key rotation")
check(
    all(parse_envelope(row[1]).key_id == "new-key" for row in rotated_rows),
    "every rotated value carries the new key id",
)
check(
    all(row[2] is None or parse_envelope(row[2]).key_id == "new-key" for row in rotated_rows),
    "every rotated provenance field carries the new key id",
)
meta = metadata(path)
check(meta["protection_key_id"] == "new-key", "database metadata records active key id")
check(meta["protection_rotation_generation"] == "1", "database metadata records rotation generation")
check("protection_compaction_pending" not in meta, "completed rotation clears compaction marker")

store.close()
with open(path, "rb") as handle:
    database_bytes = handle.read()
check(old_serialized.encode("utf-8") not in database_bytes, "VACUUM removes old serialized envelopes from database pages")
rejects(lambda: MemoryStore(path, protector=old), "old protector cannot reopen the rotated store")
reopened = MemoryStore(path, protector=new)
check(reopened.get(private.id).value == "rotation-private-value", "new protector reopens rotated store")
no_op = reopened.rotate_protection(new)
check(no_op["no_op"] and no_op["rotated_records"] == 0, "same provider/key rotation is an explicit no-op")
check(no_op["generation"] == 1, "no-op rotation does not increment generation")

scope_key = TestMemoryProtector(key=b"rotation-scope-key", key_id="scope-key")
scope_result = reopened.rotate_protection(scope_key, rotate_scope=True)
check(scope_result["rotated_records"] == 2, "scope rotation rewrites every sensitive record")
check(scope_result["new_store_scope"] != old_scope, "scope rotation creates a fresh database scope")
check(scope_result["generation"] == 2, "scope rotation increments generation")
with sqlite3.connect(path) as db:
    active_scope = db.execute(
        "SELECT value FROM agent_memory_meta WHERE key='store_scope'"
    ).fetchone()[0]
check(active_scope == scope_result["new_store_scope"], "new scope is persisted atomically")
check(
    all(parse_envelope(row[1]).store_scope == active_scope for row in raw_rows(path)),
    "every value envelope is bound to the new scope",
)
reopened.close()
rejects(lambda: MemoryStore(path, protector=new), "pre-scope-rotation protector cannot reopen the store")
scoped = MemoryStore(path, protector=scope_key)
check(scoped.get(secret.id, include_deleted=True).value == "rotation-secret-value", "scope-rotated secret reopens correctly")
scoped.close()


class FailSecondSeal(TestMemoryProtector):
    def __init__(self):
        super().__init__(key=b"rotation-failing-key", key_id="failing-key")
        self.calls = 0

    def seal(self, plaintext: bytes, *, scope: bytes):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected rotation failure")
        return super().seal(plaintext, scope=scope)


rollback_path = os.path.join(root, "rollback.db")
rollback_old = TestMemoryProtector(key=b"rollback-old-key", key_id="rollback-old")
rollback = MemoryStore(rollback_path, protector=rollback_old)
rollback_record = rollback.create(
    subject="anders",
    predicate="rollback",
    value="rollback-sensitive-value",
    sensitivity="private",
    source_ref="rollback:source",
)
rows_before = raw_rows(rollback_path)
meta_before = metadata(rollback_path)
rejects(
    lambda: rollback.rotate_protection(FailSecondSeal(), rotate_scope=True),
    "seal failure aborts the complete key/scope rotation",
)
check(raw_rows(rollback_path) == rows_before, "failed rotation leaves every envelope unchanged")
check(metadata(rollback_path) == meta_before, "failed rotation leaves scope and generation unchanged")
check(rollback.get(rollback_record.id).value == "rollback-sensitive-value", "failed rotation keeps old protector active")
rollback.close()

pending_path = os.path.join(root, "pending-compaction.db")
pending_old = TestMemoryProtector(key=b"pending-old-key", key_id="pending-old")
pending_new = TestMemoryProtector(key=b"pending-new-key", key_id="pending-new")
pending = MemoryStore(pending_path, protector=pending_old)
pending_record = pending.create(
    subject="anders",
    predicate="pending",
    value="pending-sensitive-value",
    sensitivity="private",
)
real_compact = pending._compact_after_sensitive_migration
pending._compact_after_sensitive_migration = lambda: (_ for _ in ()).throw(
    MemoryStoreError("injected compaction failure")
)
pending_result = pending.rotate_protection(pending_new)
check(pending_result["compaction_pending"], "post-commit compaction failure is reported honestly")
check(metadata(pending_path)["protection_compaction_pending"] == "1", "failed compaction leaves durable retry marker")
check(pending.get(pending_record.id).value == "pending-sensitive-value", "committed rotation remains usable after compaction failure")
pending._compact_after_sensitive_migration = real_compact
pending.close()
recovered = MemoryStore(pending_path, protector=pending_new)
check(recovered.get(pending_record.id).value == "pending-sensitive-value", "reopen resumes committed rotation")
check("protection_compaction_pending" not in metadata(pending_path), "reopen completes pending compaction and clears marker")
recovered.close()


class MissingIdentity:
    def seal(self, plaintext: bytes, *, scope: bytes):
        raise AssertionError("invalid protector must be rejected before seal")

    def open(self, payload, *, scope: bytes):
        raise AssertionError("invalid protector must be rejected before open")


identity_path = os.path.join(root, "missing-identity.db")
identity_store = MemoryStore(identity_path, protector=TestMemoryProtector())
identity_store.create(
    subject="anders",
    predicate="identity",
    value="identity-sensitive-value",
    sensitivity="private",
)
rejects(lambda: identity_store.rotate_protection(MissingIdentity()), "rotation protector requires provider and key id")
identity_store.close()

print(f"\n===== MEMORY PROTECTION ROTATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
