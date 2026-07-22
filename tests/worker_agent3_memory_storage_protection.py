#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import tempfile

from app.agent3.memory import MemoryStore, MemoryStoreError
from app.agent3.memory_protection import PREFIX
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


root = tempfile.mkdtemp(prefix="agent3-memory-storage-protection-")
path = os.path.join(root, "memory.db")
protector = TestMemoryProtector()
store = MemoryStore(path, protector=protector)

public = store.create(
    subject="modelrig",
    predicate="gpu",
    value="RTX 3060 12GB",
    sensitivity="public",
    source_ref="inventory:gpu",
)
private = store.create(
    subject="anders",
    predicate="madpræference",
    value="ingen fisk",
    sensitivity="private",
    source_ref="conversation:private-123",
)
secret = store.create(
    subject="anders",
    predicate="lokal_nøgle",
    value="hemmelig-værdi-987",
    sensitivity="secret",
    source_ref="local:secret-source",
)

with sqlite3.connect(path) as raw:
    raw.row_factory = sqlite3.Row
    public_row = raw.execute("SELECT * FROM agent_memories WHERE id=?", (public.id,)).fetchone()
    private_row = raw.execute("SELECT * FROM agent_memories WHERE id=?", (private.id,)).fetchone()
    secret_row = raw.execute("SELECT * FROM agent_memories WHERE id=?", (secret.id,)).fetchone()
    scope_rows = raw.execute(
        "SELECT value FROM agent_memory_meta WHERE key='store_scope'"
    ).fetchall()

check(public_row["value"] == "RTX 3060 12GB", "public memory remains ordinary local SQLite text")
check(public_row["schema_version"] == 1, "public row keeps schema version 1")
check(private_row["value"].startswith(PREFIX), "private value is stored as a protected envelope")
check(private_row["source_ref"].startswith(PREFIX), "private source reference is protected")
check(private_row["schema_version"] == 2, "private row records protected schema version 2")
check(secret_row["value"].startswith(PREFIX), "secret value is stored as a protected envelope")
check(secret_row["source_ref"].startswith(PREFIX), "secret source reference is protected")
check(len(scope_rows) == 1 and scope_rows[0][0], "database owns one persistent protection scope")
store_scope = scope_rows[0][0]

raw_text = "\n".join(
    str(value)
    for row in (private_row, secret_row)
    for value in (row["value"], row["source_ref"])
)
check("ingen fisk" not in raw_text, "private plaintext is absent from raw rows")
check("conversation:private-123" not in raw_text, "private provenance plaintext is absent")
check("hemmelig-værdi-987" not in raw_text, "secret plaintext is absent from raw rows")
check("local:secret-source" not in raw_text, "secret provenance plaintext is absent")

check(store.get(private.id).value == "ingen fisk", "authorized get opens private value")
check(
    store.get(private.id).source_ref == "conversation:private-123",
    "authorized get opens private provenance",
)
check(
    private.id in {item.id for item in store.search("fisk")},
    "private value search decrypts bounded candidates instead of querying ciphertext",
)
check(
    private.id not in {item.id for item in store.search("kaliv-protected")},
    "envelope syntax is never treated as searchable memory content",
)
check(
    secret.id not in {item.id for item in store.search("hemmelig")},
    "secret remains excluded from ordinary search",
)
check(
    secret.id in {item.id for item in store.search("hemmelig", include_secret=True)},
    "secret search requires explicit local opt-in",
)
check(
    private.id in {item.id for item in store.context_records()},
    "private local context receives opened content",
)
check(
    secret.id not in {item.id for item in store.context_records()},
    "secret remains excluded from ordinary context",
)

corrected = store.correct(
    private.id,
    value="ingen fisk eller sushi",
    source_ref="conversation:private-456",
)
with sqlite3.connect(path) as raw:
    corrected_row = raw.execute(
        "SELECT value,source_ref,schema_version FROM agent_memories WHERE id=?",
        (corrected.id,),
    ).fetchone()
check(corrected.value == "ingen fisk eller sushi", "correction returns opened private content")
check(corrected_row[0].startswith(PREFIX), "corrected private value is protected before insert")
check(corrected_row[1].startswith(PREFIX), "corrected private provenance is protected before insert")
check(corrected_row[2] == 2, "corrected private row remains schema v2")

deleted = store.delete(corrected.id)
check(deleted.value == "" and deleted.source_ref is None, "delete still creates a content-free tombstone")
store.close()

file_bytes = b""
for candidate in (path, path + "-wal", path + "-shm"):
    if os.path.exists(candidate):
        with open(candidate, "rb") as handle:
            file_bytes += handle.read()
check("ingen fisk".encode("utf-8") not in file_bytes, "private plaintext is absent from database files")
check("hemmelig-værdi-987".encode("utf-8") not in file_bytes, "secret plaintext is absent from database files")

reopened = MemoryStore(path, protector=protector)
check(reopened.get(private.id).value == "ingen fisk", "same protector reopens persisted private memory")
with sqlite3.connect(path) as raw:
    reopened_scope = raw.execute(
        "SELECT value FROM agent_memory_meta WHERE key='store_scope'"
    ).fetchone()[0]
check(reopened_scope == store_scope, "reopen preserves the database protection scope")
reopened.close()

wrong = MemoryStore(path, protector=TestMemoryProtector(key=b"different-memory-test-key"))
rejects(lambda: wrong.get(private.id), "wrong protector cannot open a private record")
wrong.close()

copy_path = os.path.join(root, "scope-copy.db")
copy_store = MemoryStore(copy_path, protector=protector)
with sqlite3.connect(path) as source, sqlite3.connect(copy_path) as destination:
    row = source.execute("SELECT * FROM agent_memories WHERE id=?", (private.id,)).fetchone()
    destination.execute(
        "INSERT INTO agent_memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        row,
    )
    destination.commit()
rejects(lambda: copy_store.get(private.id), "ciphertext copied into another database scope is rejected")
copy_store.close()

if os.name != "nt":
    locked_path = os.path.join(root, "locked.db")
    locked = MemoryStore(locked_path)
    operational = locked.create(
        subject="modelrig",
        predicate="status",
        value="klar",
        sensitivity="operational",
    )
    check(operational.value == "klar", "non-sensitive memory remains available without DPAPI")
    rejects(
        lambda: locked.create(
            subject="anders",
            predicate="private",
            value="må ikke falde tilbage",
            sensitivity="private",
        ),
        "non-Windows sensitive write fails closed without plaintext fallback",
    )
    locked.close()

print(f"\n===== MEMORY STORAGE PROTECTION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
