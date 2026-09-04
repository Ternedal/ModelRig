"""Kaliv backup/restore -- full persistent-state round trip.

The migration contract is stronger than "the code runs": create realistic state
for every current persistent store, back it up, wipe it, restore it and compare
the bytes. The failure cases also prove corrupt archives and silent clobber are
refused.

Run: PYTHONPATH=worker python3 tests/worker_backup.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-test-")
# One stable root exercises the same defaults used by a real Windows rig. The
# backend pairing file and notes have their own authoritative locations.
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data-root")
os.environ["MODELRIG_DATA"] = os.path.join(_root, "backend", "modelrig-data.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def _seed_sqlite(path: str, key: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    if key == "rag.db":
        con.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT)")
        con.executemany(
            "INSERT INTO docs (body) VALUES (?)",
            [("chunk %d" % i,) for i in range(200)],
        )
    else:
        con.execute("CREATE TABLE state (name TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO state(name, value) VALUES (?, ?)", (key, "seeded"))
    con.commit()
    con.close()


def seed():
    """Write realistic state to every current file plus nested notes."""
    for it in backup.items():
        if it.kind == "dir":
            os.makedirs(it.path, exist_ok=True)
            with open(os.path.join(it.path, "notes.md"), "w", encoding="utf-8") as f:
                f.write("## 2026-09-04 17:00\nMigration test\n")
            sub = os.path.join(it.path, "sub")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, "deep.md"), "w", encoding="utf-8") as f:
                f.write("nested\n")
            continue

        os.makedirs(os.path.dirname(os.path.abspath(it.path)), exist_ok=True)
        if it.path.lower().endswith(".db"):
            _seed_sqlite(it.path, it.key)
        else:
            with open(it.path, "w", encoding="utf-8") as f:
                f.write('{"key":"%s","seeded":true}' % it.key)


def snapshot() -> dict:
    """sha256 of every persistent file, for a byte-for-byte before/after."""
    out = {}
    for it in backup.items():
        if it.kind == "file" and os.path.exists(it.path):
            with open(it.path, "rb") as f:
                out[it.key] = hashlib.sha256(f.read()).hexdigest()
        elif it.kind == "dir" and os.path.isdir(it.path):
            for path in backup._walk(it.path):
                rel = os.path.relpath(path, it.path)
                with open(path, "rb") as f:
                    out[f"{it.key}/{rel}"] = hashlib.sha256(f.read()).hexdigest()
    return out


def wipe():
    for it in backup.items():
        if it.kind == "file" and os.path.exists(it.path):
            os.remove(it.path)
        elif it.kind == "dir" and os.path.isdir(it.path):
            shutil.rmtree(it.path)


def archive_with_schema(source: str, destination: str, schema: int) -> None:
    """Copy an archive while changing only manifest.schema."""
    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:
        for member in src.getmembers():
            extracted = src.extractfile(member)
            data = extracted.read() if extracted else b""
            if member.name == "manifest.json":
                manifest = json.loads(data)
                manifest["schema"] = schema
                data = json.dumps(manifest, indent=2, sort_keys=True).encode()
            replacement = tarfile.TarInfo(member.name)
            replacement.size = len(data)
            dst.addfile(replacement, io.BytesIO(data))


# --- inventory --------------------------------------------------------------
required_keys = {
    "rag.db",
    "data.json",
    "audit.db",
    "tools-state.json",
    "jobs.db",
    "schedules.db",
    "agent3-runs.db",
    "agent3-read-reviews.db",
    "agent3-replans.db",
    "agent3-replan-previews.db",
    "agent3-memory.db",
    "agent3-memory-grants.db",
    "agent3-plans.db",
    "agent3-task-plans.db",
    "agent3-approvals.db",
    "home-rig-grants.db",
    "home-rig-audit.db",
    "data-sharing.db",
    "notes",
}
actual_keys = {it.key for it in backup.items()}
check(required_keys <= actual_keys, "inventory: every current persistent store is covered")
check(
    next(it for it in backup.items() if it.key == "data.json").path == os.environ["MODELRIG_DATA"],
    "inventory: backend pairing state follows MODELRIG_DATA",
)

# --- the round trip ---------------------------------------------------------
seed()
before = snapshot()
check(len(before) == len(required_keys) + 1, "seed: every store plus two note files exists")

archive = backup.create(os.path.join(_root, "backups"))
check(os.path.exists(archive), "create: archive written")
check(archive.endswith(".tar.gz"), "create: archive is a gzip tarball")
check(not os.path.exists(archive + ".tmp"), "create: no leftover temp file")
manifest = backup._read_manifest(archive)
check(manifest["schema"] == 2, "schema: expanded 2.x inventory writes schema 2")
check(1 in backup.SUPPORTED_BACKUP_SCHEMAS, "schema: current code retains schema-1 restore compatibility")

verified = backup.verify(archive)
check(verified["ok"], "verify: a fresh backup passes its own hashes")
check(verified["checked"] == len(before), "verify: every seeded file is in the archive")

# A schema-1 archive remains readable by new code, while new archives no longer
# masquerade as schema 1 to old code that cannot know the expanded inventory.
legacy = os.path.join(_root, "legacy-schema-1.tar.gz")
archive_with_schema(archive, legacy, 1)
check(backup.verify(legacy)["ok"], "schema: current code still verifies legacy schema 1")
future = os.path.join(_root, "unsupported-schema.tar.gz")
archive_with_schema(archive, future, 999)
try:
    backup.verify(future)
    check(False, "schema: unknown future schema is refused")
except ValueError:
    check(True, "schema: unknown future schema is refused")

wipe()
check(snapshot() == {}, "wipe: live state is gone")

restored = backup.restore(archive)
check(len(restored["restored"]) == len(before), "restore: every file came back")

after = snapshot()
check(after == before, "restore: byte-for-byte identical to before")

# Every restored sqlite store must still be structurally readable.
for it in backup.items():
    if it.kind != "file" or not it.path.lower().endswith(".db"):
        continue
    con = sqlite3.connect(it.path)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    check(integrity == "ok", f"restore: sqlite integrity is OK for {it.key}")

con = sqlite3.connect(next(it.path for it in backup.items() if it.key == "rag.db"))
count = con.execute("SELECT count(*) FROM docs").fetchone()[0]
con.close()
check(count == 200, "restore: RAG database still contains all 200 rows")

# --- failure modes ----------------------------------------------------------
# A corrupt archive must be refused, not half-applied.
bad = os.path.join(_root, "corrupt.tar.gz")
with tarfile.open(archive, "r:gz") as src, tarfile.open(bad, "w:gz") as dst:
    for member in src.getmembers():
        extracted = src.extractfile(member)
        data = extracted.read() if extracted else b""
        if member.name == "data/rag.db":
            data = data[:-50] + b"\x00" * 50
        replacement = tarfile.TarInfo(member.name)
        replacement.size = len(data)
        dst.addfile(replacement, io.BytesIO(data))

bad_verify = backup.verify(bad)
check(not bad_verify["ok"], "verify: a tampered file is caught")
check(any("rag.db" in p for p in bad_verify["problems"]), "verify: names the tampered file")

wipe()
try:
    backup.restore(bad)
    check(False, "restore: a corrupt archive is refused")
except ValueError:
    check(True, "restore: a corrupt archive is refused")
check(snapshot() == {}, "restore: a refused restore wrote NOTHING")

# Without --force, a restore must not clobber an existing rig.
backup.restore(archive)
try:
    backup.restore(archive)
    check(False, "restore: refuses to overwrite without --force")
except FileExistsError:
    check(True, "restore: refuses to overwrite without --force")

forced = backup.restore(archive, force=True)
check(len(forced["restored"]) == len(before), "restore --force: overwrites cleanly")

# An empty rig is still a valid backup.
wipe()
empty = backup.create(os.path.join(_root, "empty"))
check(backup.verify(empty)["ok"], "create: an empty rig produces a valid empty backup")
check(backup._read_manifest(empty)["schema"] == 2, "create: empty rig still emits current schema 2")

# --- complete-rig orchestration contract -----------------------------------
# Keep this in the existing backup test instead of adding a new tests/*.py file:
# generated CURRENT_STATE inventory is itself a drift gate. The repository-wide
# PowerShell syntax gate parses the operator; these checks lock the sequencing
# choices that make the two independently tested child migrations coherent.
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
complete_operator = os.path.join(repo_root, "scripts", "migrate-complete-rig.ps1")
check(os.path.isfile(complete_operator), "complete migration: top-level operator exists")
if os.path.isfile(complete_operator):
    complete_text = open(complete_operator, "r", encoding="utf-8-sig").read()
    check(
        '"complete-rig-migration/v1"' in complete_text,
        "complete migration: bundle schema is explicit",
    )
    check(
        '"-SkipRestart"' in complete_text
        and "holding ModelRig stopped" in complete_text
        and "while ModelRig remains stopped" in complete_text,
        "complete migration: ModelRig stays down across the VoiceRig snapshot boundary",
    )
    check(
        "ModelRig state export" in complete_text
        and "VoiceRig state export" in complete_text
        and complete_text.index("ModelRig state export") < complete_text.index("VoiceRig state export"),
        "complete migration: ModelRig snapshot precedes VoiceRig shared-voice snapshot",
    )
    check(
        '"-SkipValidation"' in complete_text
        and "VoiceRig state import" in complete_text
        and "Final new-rig validation" in complete_text
        and complete_text.index("VoiceRig state import") < complete_text.index("Final new-rig validation"),
        "complete migration: one final validation runs after both child imports",
    )
    check(
        "manual_inputs_not_bundled" in complete_text
        and "ModelRig/VoiceRig secret values and credentials" in complete_text
        and "BodyRig licensed SMPL/SMPL-X assets" in complete_text,
        "complete migration: secrets and licensed BodyRig assets stay explicit manual inputs",
    )
    check(
        "Complete import is PARTIAL" in complete_text,
        "complete migration: partial child success is never called cutover-ready",
    )

print(f"\n===== BACKUP: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)