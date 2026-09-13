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
    elif key == backup.AGENT3_RUNS_KEY:
        con.execute(
            "CREATE TABLE agent_runs ("
            "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
            ("backup-run", "running", "{}", 1.0),
        )
    elif key == backup.AGENT3_EXECUTION_PROGRESS_KEY:
        con.execute(
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
        )
        con.execute(
            "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) "
            "VALUES(?,?,?,?)",
            ("backup-run", 0, "a" * 64, 1.0),
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
        if it.key.endswith(".db"):
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


def archive_with_schema(
    source: str,
    destination: str,
    schema: int,
    drop_keys=(),
    replace_files=None,
) -> None:
    """Copy an archive while changing manifest.schema and optionally dropping keys."""
    drop_keys = set(drop_keys)
    replace_files = dict(replace_files or {})
    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:
        for member in src.getmembers():
            if member.name.startswith("data/") and member.name.removeprefix("data/") in drop_keys:
                continue
            extracted = src.extractfile(member)
            data = extracted.read() if extracted else b""
            data_key = member.name.removeprefix("data/") if member.name.startswith("data/") else None
            if data_key in replace_files:
                data = replace_files[data_key]
            if member.name == "manifest.json":
                manifest = json.loads(data)
                manifest["schema"] = schema
                for key in drop_keys:
                    manifest["files"].pop(key, None)
                for key, replacement in replace_files.items():
                    if key in manifest["files"]:
                        manifest["files"][key]["sha256"] = hashlib.sha256(replacement).hexdigest()
                data = json.dumps(manifest, indent=2, sort_keys=True).encode()
            replacement = tarfile.TarInfo(member.name)
            replacement.size = len(data)
            dst.addfile(replacement, io.BytesIO(data))


def execution_progress_bytes_with_erasing_trigger() -> bytes:
    fd, path = tempfile.mkstemp(prefix="kaliv-trigger-progress-", suffix=".db")
    os.close(fd)
    try:
        _seed_sqlite(path, backup.AGENT3_EXECUTION_PROGRESS_KEY)
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TRIGGER erase_execution_start AFTER INSERT ON agent_execution_starts "
            "BEGIN DELETE FROM agent_execution_starts "
            "WHERE run_id=NEW.run_id AND step_index=NEW.step_index "
            "AND step_sha256=NEW.step_sha256; END"
        )
        con.commit()
        con.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass



def execution_progress_bytes_with_rejecting_check() -> bytes:
    fd, path = tempfile.mkstemp(prefix="kaliv-check-progress-", suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, "
            "PRIMARY KEY(run_id,step_index,step_sha256), CHECK(0))"
        )
        con.commit()
        con.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


# --- inventory --------------------------------------------------------------
required_keys = {
    "rag.db",
    "data.json",
    "audit.db",
    "tools-state.json",
    "jobs.db",
    "schedules.db",
    "agent3-runs.db",
    "agent3-execution-progress.db",
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
runs_item = next(it for it in backup.items() if it.key == "agent3-runs.db")
progress_item = next(it for it in backup.items() if it.key == "agent3-execution-progress.db")
check(
    progress_item.path == runs_item.path + ".execution-progress",
    "inventory: Agent3 execution authority follows the exact resolved run DB path",
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
check(manifest["schema"] == 3, "schema: execution-authority inventory writes schema 3")
check(1 in backup.SUPPORTED_BACKUP_SCHEMAS, "schema: current code retains schema-1 read compatibility")
check(2 in backup.SUPPORTED_BACKUP_SCHEMAS, "schema: current code retains schema-2 read compatibility")
check(
    "agent3-execution-progress.db" in manifest["files"],
    "create: execution-progress authority is present beside Agent3 runs",
)

verified = backup.verify(archive)
check(verified["ok"], "verify: a fresh backup passes its own hashes and authority relation")
check(verified["checked"] == len(before), "verify: every seeded file is in the archive")

# Legacy schema numbers remain readable only when the archive actually carries
# the execution authority required by any Agent3 run state it contains.
legacy = os.path.join(_root, "legacy-schema-1.tar.gz")
archive_with_schema(archive, legacy, 1)
check(backup.verify(legacy)["ok"], "schema: legacy schema 1 with complete execution authority still verifies")

unsafe_legacy = os.path.join(_root, "unsafe-schema-2-without-progress.tar.gz")
archive_with_schema(
    archive,
    unsafe_legacy,
    2,
    drop_keys={"agent3-execution-progress.db"},
)
unsafe_verify = backup.verify(unsafe_legacy)
check(not unsafe_verify["ok"], "schema: Agent3 runs without execution authority are refused")
check(
    any("execution-progress authority" in problem for problem in unsafe_verify["problems"]),
    "schema: unsafe legacy archive names the missing execution authority",
)
pre_unsafe_restore = snapshot()
try:
    backup.restore(unsafe_legacy, force=True)
    check(False, "restore: unsafe legacy Agent3 archive is refused")
except ValueError:
    check(True, "restore: unsafe legacy Agent3 archive is refused")
check(snapshot() == pre_unsafe_restore, "restore: unsafe legacy refusal writes NOTHING")

# A sidecar whose bytes hash correctly but which is not the execution-authority
# SQLite schema must still fail verification. Hashes prove transport integrity,
# not authority semantics.
invalid_progress = os.path.join(_root, "invalid-execution-progress.tar.gz")
archive_with_schema(
    archive,
    invalid_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: b""},
)
invalid_progress_verify = backup.verify(invalid_progress)
check(
    not invalid_progress_verify["ok"],
    "verify: empty execution-progress sidecar is refused even when its manifest hash matches",
)
check(
    any("execution-progress authority" in problem for problem in invalid_progress_verify["problems"]),
    "verify: invalid execution-progress sidecar names the authority failure",
)
pre_invalid_restore = snapshot()
try:
    backup.restore(invalid_progress, force=True)
    check(False, "restore: invalid execution-progress authority is refused")
except ValueError:
    check(True, "restore: invalid execution-progress authority is refused")
check(snapshot() == pre_invalid_restore, "restore: invalid authority refusal writes NOTHING")

# A syntactically valid sidecar can still be unsafe if extra schema objects can
# mutate watermark semantics. In particular, an AFTER INSERT trigger can erase
# the just-inserted execution marker while all expected columns/PKs and
# integrity_check remain valid. The dedicated authority DB therefore admits no
# user-defined object other than the canonical table.
trigger_progress_bytes = execution_progress_bytes_with_erasing_trigger()
trigger_progress = os.path.join(_root, "trigger-execution-progress.tar.gz")
archive_with_schema(
    archive,
    trigger_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: trigger_progress_bytes},
)
trigger_verify = backup.verify(trigger_progress)
check(
    not trigger_verify["ok"],
    "verify: trigger-bearing execution-progress sidecar is refused with matching manifest hash",
)
check(
    any("unexpected user-defined schema objects" in problem for problem in trigger_verify["problems"]),
    "verify: trigger-bearing sidecar names the closed-schema authority failure",
)
pre_trigger_restore = snapshot()
try:
    backup.restore(trigger_progress, force=True)
    check(False, "restore: trigger-bearing execution-progress authority is refused")
except ValueError:
    check(True, "restore: trigger-bearing execution-progress authority is refused")
check(
    snapshot() == pre_trigger_restore,
    "restore: trigger-bearing authority refusal writes NOTHING",
)

# Inline constraints are part of execution authority even though they do not
# appear as separate sqlite_master objects and table_xinfo exposes the same
# visible columns/PK. CHECK(0) combined with INSERT OR IGNORE can silently drop
# every execution watermark, so only the canonical CREATE TABLE SQL is accepted.
check_progress_bytes = execution_progress_bytes_with_rejecting_check()
check_progress = os.path.join(_root, "check-constrained-execution-progress.tar.gz")
archive_with_schema(
    archive,
    check_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: check_progress_bytes},
)
check_verify = backup.verify(check_progress)
check(
    not check_verify["ok"],
    "verify: CHECK-constrained execution-progress sidecar is refused with matching manifest hash",
)
check(
    any("canonical CREATE TABLE authority" in problem for problem in check_verify["problems"]),
    "verify: inline constraint failure names canonical table authority",
)
pre_check_restore = snapshot()
try:
    backup.restore(check_progress, force=True)
    check(False, "restore: CHECK-constrained execution-progress authority is refused")
except ValueError:
    check(True, "restore: CHECK-constrained execution-progress authority is refused")
check(
    snapshot() == pre_check_restore,
    "restore: CHECK-constrained authority refusal writes NOTHING",
)

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

# Every restored sqlite store must still be structurally readable, including
# the execution-progress sidecar whose filename itself does not end in .db.
for it in backup.items():
    if it.kind != "file" or not it.key.endswith(".db"):
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

# A malformed execution sidecar must be refused before a backup is created.
wipe()
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(b"")
try:
    backup.create(os.path.join(_root, "invalid-progress-create"))
    check(False, "create: invalid execution-progress authority is refused")
except ValueError:
    check(True, "create: invalid execution-progress authority is refused")
wipe()

# A structurally correct live sidecar with an erasing trigger must also be
# rejected before create can publish a backup.
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(trigger_progress_bytes)
try:
    backup.create(os.path.join(_root, "trigger-progress-create"))
    check(False, "create: trigger-bearing execution-progress authority is refused")
except ValueError:
    check(True, "create: trigger-bearing execution-progress authority is refused")
wipe()

# A structurally correct live sidecar with an inline constraint that suppresses
# watermark insertion must be rejected before create can publish a backup.
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(check_progress_bytes)
try:
    backup.create(os.path.join(_root, "check-progress-create"))
    check(False, "create: CHECK-constrained execution-progress authority is refused")
except ValueError:
    check(True, "create: CHECK-constrained execution-progress authority is refused")
wipe()

# A non-empty run database without its execution authority must never produce a new backup.
_seed_sqlite(runs_item.path, runs_item.key)
try:
    backup.create(os.path.join(_root, "missing-progress"))
    check(False, "create: Agent3 runs without execution-progress sidecar are refused")
except ValueError:
    check(True, "create: Agent3 runs without execution-progress sidecar are refused")
wipe()

# Legacy schema 1/2 archives may legitimately contain an initialized but empty
# Agent3 run store: no execution has crossed the boundary, so no progress
# sidecar authority exists yet and no replay risk is introduced.
os.makedirs(os.path.dirname(runs_item.path), exist_ok=True)
con = sqlite3.connect(runs_item.path)
con.execute(
    "CREATE TABLE agent_runs ("
    "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
)
con.commit()
con.close()
empty_runs_archive = backup.create(os.path.join(_root, "empty-agent3-runs"))
check(
    backup.verify(empty_runs_archive)["ok"],
    "create: initialized empty Agent3 run store does not require a progress sidecar",
)
legacy_empty_runs = os.path.join(_root, "legacy-schema-2-empty-agent3-runs.tar.gz")
archive_with_schema(empty_runs_archive, legacy_empty_runs, 2)
check(
    backup.verify(legacy_empty_runs)["ok"],
    "schema: legacy empty Agent3 run store remains compatible without a progress sidecar",
)
wipe()

# An empty rig is still a valid backup.
empty = backup.create(os.path.join(_root, "empty"))
check(backup.verify(empty)["ok"], "create: an empty rig produces a valid empty backup")
check(backup._read_manifest(empty)["schema"] == 3, "create: empty rig still emits current schema 3")

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
    import_region = complete_text[complete_text.index("$modelImported = $false") :]
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
        '"-SkipValidation",\n        "-SkipRestart"' in import_region
        and "Assert-ModelRigStopped" in import_region
        and "VoiceRig state import" in import_region,
        "complete migration: ModelRig child import stays stopped through VoiceRig restore",
    )
    check(
        "$voiceImported = $true\n    Assert-ModelRigStopped\n\n    Write-Step \"Starting restored ModelRig through recovery-first bootstrap\"\n    Resume-HeldModelRig"
        in import_region,
        "complete migration: recovery-first ModelRig restart happens only after VoiceRig restore",
    )
    check(
        "Assert-CanonicalModelRigRuntime" in complete_text
        and "requires ModelRigRuntimeRoot to equal InstallRoot" in complete_text
        and "standalone ModelRig migration operator for non-canonical layouts" in complete_text,
        "complete migration: custom runtime cannot make final validation inspect another appliance",
    )
    check(
        "VoiceRig state import" in import_region
        and "Final new-rig validation" in import_region
        and '"-SkipBodyRig"' in import_region
        and import_region.index("VoiceRig state import") < import_region.index("Final new-rig validation"),
        "complete migration: one core validation runs after both child imports",
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

bootstrap_operator = os.path.join(repo_root, "scripts", "bootstrap-new-rig.ps1")
check(os.path.isfile(bootstrap_operator), "new-rig bootstrap: operator exists")
if os.path.isfile(bootstrap_operator):
    bootstrap_text = open(bootstrap_operator, "r", encoding="utf-8-sig").read()
    check(
        'http://127.0.0.1:8765/api/readiness' in bootstrap_text,
        "new-rig bootstrap: VoiceRig readiness uses authoritative port 8765",
    )
    check(
        'http://127.0.0.1:8079/api/readiness' not in bootstrap_text,
        "new-rig bootstrap: stale VoiceRig port 8079 cannot return",
    )

print(f"\n===== BACKUP: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
