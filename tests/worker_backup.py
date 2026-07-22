"""Kaliv backup/restore -- the round trip V7's exit criterion demands.

"restore fra backup er bevist én gang" (ROADMAP V7). Proving it means more than
"the code runs": back up real state, destroy it, restore, and check the result
is byte-for-byte what was there before. Plus the failure modes that make a
backup dangerous -- a corrupt archive, a clobbered rig -- because a restore tool
that cheerfully writes garbage over live data is worse than none.

Run: PYTHONPATH=worker python3 tests/worker_backup.py
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import tarfile
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-test-")
# Point every persistent location at the sandbox BEFORE importing the module.
os.environ["MODELRIG_DB"] = os.path.join(_root, "rag.db")
os.environ["MODELRIG_DATA_PATH"] = os.path.join(_root, "data.json")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_root, "audit.db")
os.environ["KALIV_AGENT3_MEMORY_DB"] = os.path.join(_root, "agent3-memory.db")
os.environ["KALIV_TOOLS_STATE"] = os.path.join(_root, "tools-state.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402
from app.agent3.memory import MemoryStore  # noqa: E402
from helpers.memory_protector import TestMemoryProtector  # noqa: E402

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS: {name}")
    else:
        failed += 1; print(f"  FAIL: {name}")


def seed():
    """Write realistic state, including protected memory in a live WAL DB."""
    con = sqlite3.connect(os.environ["MODELRIG_DB"])
    con.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO docs (body) VALUES (?)",
                    [("chunk %d" % i,) for i in range(200)])
    con.commit(); con.close()

    with open(os.environ["MODELRIG_DATA_PATH"], "w", encoding="utf-8") as f:
        f.write('{"devices":[{"id":"pixel","token_hash":"deadbeef"}]}')

    with open(os.environ["KALIV_TOOLS_STATE"], "w", encoding="utf-8") as f:
        f.write('{"enabled": false, "disabled_tools": ["note_append"]}')

    os.makedirs(os.environ["KALIV_TOOLS_DIR"], exist_ok=True)
    with open(os.path.join(os.environ["KALIV_TOOLS_DIR"], "notes.md"), "w", encoding="utf-8") as f:
        f.write("## 2026-07-10 12:00\nHusk mælk\n")
    # A nested file, to prove directory walking is not one level deep.
    sub = os.path.join(os.environ["KALIV_TOOLS_DIR"], "sub")
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, "deep.md"), "w", encoding="utf-8") as f:
        f.write("nested\n")

    protector = TestMemoryProtector()
    memory = MemoryStore(os.environ["KALIV_AGENT3_MEMORY_DB"], protector=protector)
    record = memory.create(
        subject="anders",
        predicate="backup-test",
        value="privat-backup-værdi-7431",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="backup:test-private-source",
        review_status="confirmed",
    )
    # Keep the writer open: backup must include committed WAL state, not merely
    # whatever happened to be checkpointed into the main database file.
    with sqlite3.connect(os.environ["KALIV_AGENT3_MEMORY_DB"]) as raw:
        store_scope = raw.execute(
            "SELECT value FROM agent_memory_meta WHERE key='store_scope'"
        ).fetchone()[0]
    return memory, protector, record.id, store_scope


def _sqlite_logical_sha(path: str) -> str:
    con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        payload = "\n".join(con.iterdump()).encode("utf-8")
    finally:
        con.close()
    return hashlib.sha256(payload).hexdigest()


def snapshot() -> dict:
    """Digest every persistent item; SQLite items use logical WAL-aware state."""
    out = {}
    for it in backup.items():
        if it.kind == "sqlite" and os.path.exists(it.path):
            out[it.key] = _sqlite_logical_sha(it.path)
        elif it.kind == "file" and os.path.exists(it.path):
            out[it.key] = hashlib.sha256(open(it.path, "rb").read()).hexdigest()
        elif it.kind == "dir" and os.path.isdir(it.path):
            for f in backup._walk(it.path):
                rel = os.path.relpath(f, it.path)
                out[f"{it.key}/{rel}"] = hashlib.sha256(open(f, "rb").read()).hexdigest()
    return out


def wipe():
    import shutil
    for it in backup.items():
        if it.kind in {"file", "sqlite"} and os.path.exists(it.path):
            os.remove(it.path)
        elif it.kind == "dir" and os.path.isdir(it.path):
            shutil.rmtree(it.path)


# --- the round trip ---------------------------------------------------------
memory_store, memory_protector, memory_id, memory_scope = seed()
before = snapshot()
check(len(before) >= 6, "seed: real state exists, including protected memory")

archive = backup.create(os.path.join(_root, "backups"))
check(os.path.exists(archive), "create: archive written")
check(archive.endswith(".tar.gz"), "create: archive is a gzip tarball")
check(not os.path.exists(archive + ".tmp"), "create: no leftover temp file")

with tarfile.open(archive, "r:gz") as tar:
    member = tar.extractfile("data/agent3-memory.db")
    memory_backup_bytes = member.read() if member else b""
check(bool(memory_backup_bytes), "create: protected memory SQLite snapshot is included")
check(
    b"privat-backup-v" + bytes([0xc3, 0xa6]) + b"rdi-7431" not in memory_backup_bytes,
    "create: memory backup contains no private plaintext",
)
check(
    b"backup:test-private-source" not in memory_backup_bytes,
    "create: memory backup contains no private provenance plaintext",
)

v = backup.verify(archive)
check(v["ok"], "verify: a fresh backup passes its own hashes")
check(v["checked"] == len(before), "verify: every seeded file is in the archive")

# Close only after create: the successful restore below proves the online backup
# captured the committed row while the original WAL connection was alive.
memory_store.close()
wipe()
check(snapshot() == {}, "wipe: live state is gone")

res = backup.restore(archive)
check(len(res["restored"]) == len(before), "restore: every file came back")

after = snapshot()
check(after == before, "restore: logical state is identical to before")

# The restored sqlite databases are not just bytes -- they still open and retain
# both ordinary rows and DPAPI/envelope scope identity.
con = sqlite3.connect(os.environ["MODELRIG_DB"])
n = con.execute("SELECT count(*) FROM docs").fetchone()[0]
con.close()
check(n == 200, "restore: the RAG sqlite db still opens and has all 200 rows")

restored_memory = MemoryStore(
    os.environ["KALIV_AGENT3_MEMORY_DB"],
    protector=memory_protector,
)
restored_record = restored_memory.get(memory_id)
check(
    restored_record.value == "privat-backup-værdi-7431",
    "restore: same protector opens the latest WAL-backed private memory",
)
with sqlite3.connect(os.environ["KALIV_AGENT3_MEMORY_DB"]) as raw:
    restored_scope = raw.execute(
        "SELECT value FROM agent_memory_meta WHERE key='store_scope'"
    ).fetchone()[0]
check(restored_scope == memory_scope, "restore: protected database store_scope is preserved")
restored_memory.close()

# --- failure modes ----------------------------------------------------------

# A corrupt archive must be refused, not half-applied.
bad = os.path.join(_root, "corrupt.tar.gz")
with tarfile.open(archive, "r:gz") as src, tarfile.open(bad, "w:gz") as dst:
    for m in src.getmembers():
        f = src.extractfile(m)
        data = f.read() if f else b""
        if m.name == "data/rag.db":
            data = data[:-50] + b"\x00" * 50  # tamper the body, keep the manifest
        import io as _io
        m2 = tarfile.TarInfo(m.name); m2.size = len(data)
        dst.addfile(m2, _io.BytesIO(data))
vr = backup.verify(bad)
check(not vr["ok"], "verify: a tampered file is caught")
check(any("rag.db" in p for p in vr["problems"]), "verify: names the tampered file")

wipe()
try:
    backup.restore(bad)
    check(False, "restore: a corrupt archive is refused")
except ValueError:
    check(True, "restore: a corrupt archive is refused")
check(snapshot() == {}, "restore: a refused restore wrote NOTHING (no half-apply)")

# Without --force, a restore must not clobber an existing rig.
backup.restore(archive)                 # populate
try:
    backup.restore(archive)             # again, no force
    check(False, "restore: refuses to overwrite without --force")
except FileExistsError:
    check(True, "restore: refuses to overwrite without --force")
# With --force it proceeds.
res2 = backup.restore(archive, force=True)
check(len(res2["restored"]) == len(before), "restore --force: overwrites cleanly")

# A backup with nothing to back up is still a valid (empty) archive, not a crash.
wipe()
empty = backup.create(os.path.join(_root, "empty"))
check(backup.verify(empty)["ok"], "create: an empty rig produces a valid empty backup")

print(f"\n===== BACKUP: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
