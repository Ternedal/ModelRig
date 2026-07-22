#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import tempfile
import time

from app.agent3.memory import MemoryStore, MemoryStoreError
from app.agent3.memory_protection import MemoryProtectionError, PREFIX
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


def create_legacy_db(path: str, *, corrupt_v2: bool = False) -> None:
    now = time.time()
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE agent_memories (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value TEXT NOT NULL,
                kind TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                confidence REAL NOT NULL,
                review_status TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                supersedes_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                deleted_at REAL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(supersedes_id) REFERENCES agent_memories(id)
            )
            """
        )
        rows = [
            (
                "legacy-private",
                "anders",
                "preference",
                "legacy-ingen-fisk",
                "preference",
                "private",
                "user_explicit",
                "conversation:legacy-private",
                1.0,
                "confirmed",
                "active",
                None,
                now,
                now,
                None,
                None,
                2 if corrupt_v2 else 1,
            ),
            (
                "legacy-secret",
                "anders",
                "credential",
                "legacy-super-secret",
                "fact",
                "secret",
                "imported",
                "import:legacy-secret",
                0.9,
                "pending",
                "superseded",
                None,
                now,
                now,
                None,
                None,
                1,
            ),
            (
                "legacy-deleted",
                "anders",
                "old",
                "",
                "note",
                "private",
                "user_explicit",
                None,
                1.0,
                "rejected",
                "deleted",
                None,
                now,
                now,
                None,
                now,
                1,
            ),
        ]
        db.executemany(
            "INSERT INTO agent_memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()


def sensitive_rows(path: str):
    with sqlite3.connect(path) as db:
        return db.execute(
            "SELECT id,value,source_ref,schema_version,lifecycle_status "
            "FROM agent_memories WHERE sensitivity IN ('private','secret') "
            "ORDER BY id"
        ).fetchall()


root = tempfile.mkdtemp(prefix="agent3-memory-migration-")
path = os.path.join(root, "legacy.db")
create_legacy_db(path)
protector = TestMemoryProtector()
store = MemoryStore(path, protector=protector)

check(store.get("legacy-private").value == "legacy-ingen-fisk", "legacy private value opens after migration")
check(
    store.get("legacy-private").source_ref == "conversation:legacy-private",
    "legacy private provenance opens after migration",
)
check(
    store.get("legacy-secret").value == "legacy-super-secret",
    "superseded secret history is migrated and remains readable locally",
)
rows_after = sensitive_rows(path)
active_rows = [row for row in rows_after if row[4] != "deleted"]
check(all(row[1].startswith(PREFIX) for row in active_rows), "every live legacy sensitive value is protected")
check(all(row[2] is None or row[2].startswith(PREFIX) for row in active_rows), "every legacy sensitive provenance field is protected")
check(all(row[3] == 2 for row in active_rows), "migrated sensitive rows use schema version 2")
check(
    next(row for row in rows_after if row[0] == "legacy-deleted")[1:4] == ("", None, 1),
    "content-free deleted tombstone needs no encryption rewrite",
)
with sqlite3.connect(path) as db:
    meta = dict(db.execute("SELECT key,value FROM agent_memory_meta").fetchall())
check(bool(meta.get("store_scope")), "migration creates and persists a store scope")
check(meta.get("protection_schema") == "2", "migration records completed protection schema 2")
store.close()

file_bytes = b""
for candidate in (path, path + "-wal", path + "-shm"):
    if os.path.exists(candidate):
        with open(candidate, "rb") as handle:
            file_bytes += handle.read()
check(b"legacy-ingen-fisk" not in file_bytes, "migration compaction removes private plaintext from database files")
check(b"legacy-super-secret" not in file_bytes, "migration compaction removes secret plaintext from database files")
check(b"conversation:legacy-private" not in file_bytes, "migration compaction removes plaintext provenance")

ciphertexts_before = [(row[0], row[1], row[2]) for row in rows_after]
reopened = MemoryStore(path, protector=protector)
check(reopened.get("legacy-private").value == "legacy-ingen-fisk", "migrated database reopens normally")
reopened.close()
check(
    [(row[0], row[1], row[2]) for row in sensitive_rows(path)] == ciphertexts_before,
    "completed migration is idempotent and does not rewrap ciphertext",
)


class FailSecondSeal(TestMemoryProtector):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def seal(self, plaintext: bytes, *, scope: bytes):
        self.calls += 1
        if self.calls == 2:
            raise MemoryProtectionError("injected migration failure")
        return super().seal(plaintext, scope=scope)


rollback_path = os.path.join(root, "rollback.db")
create_legacy_db(rollback_path)
before_rollback = sensitive_rows(rollback_path)
rejects(
    lambda: MemoryStore(rollback_path, protector=FailSecondSeal()),
    "protector failure aborts the legacy migration",
)
after_rollback = sensitive_rows(rollback_path)
check(after_rollback == before_rollback, "failed migration leaves every legacy row unchanged")
check(
    all(not str(row[1]).startswith(PREFIX) and row[3] == 1 for row in after_rollback),
    "failed batch never commits a partially protected row",
)

corrupt_path = os.path.join(root, "corrupt-v2.db")
create_legacy_db(corrupt_path, corrupt_v2=True)
rejects(
    lambda: MemoryStore(corrupt_path, protector=protector),
    "schema v2 plaintext is treated as corruption and fails closed",
)

if os.name != "nt":
    locked_path = os.path.join(root, "no-dpapi.db")
    create_legacy_db(locked_path)
    locked_before = sensitive_rows(locked_path)
    rejects(
        lambda: MemoryStore(locked_path),
        "legacy sensitive migration fails closed when Windows DPAPI is unavailable",
    )
    check(sensitive_rows(locked_path) == locked_before, "unavailable DPAPI leaves legacy rows untouched")

print(f"\n===== MEMORY LEGACY MIGRATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
