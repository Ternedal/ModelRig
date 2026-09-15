"""Regression contract for schema-5 legacy Agent3 pair adoption.

Run: PYTHONPATH=worker python3 tests/worker_agent3_pair_adoption.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid

_root = tempfile.mkdtemp(prefix="agent3-pair-adoption-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data")
os.environ["KALIV_AGENT3_DB"] = os.path.join(_root, "live", "agent3.db")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402
from app import backup_schema5  # noqa: E402
from app.agent3 import authority_pair  # noqa: E402
from app.agent3.adopt_pair import adopt_current_pair  # noqa: E402
from app.agent3.core import (  # noqa: E402
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    Sensitivity,
    StepState,
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


def paths() -> tuple[str, str]:
    runs = next(
        item.path for item in backup.items() if item.key == backup.AGENT3_RUNS_KEY
    )
    return runs, runs + ".execution-progress"


def step_payload(state: str) -> dict:
    return {
        "tool": "append_note",
        "args": {"text": "migration"},
        "risk": "write",
        "sensitivity": "operational",
        "egress": "local",
        "origin": "local",
        "conversation_id": None,
        "idempotent": False,
        "state": state,
    }


def execution_step_sha256() -> str:
    """Use the runtime's canonical watermark digest, not a test-local copy."""
    return AgentRunStore._execution_step_sha256(
        AgentStep(
            tool="append_note",
            args={"text": "migration"},
            risk=RiskClass.WRITE,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.LOCAL,
            origin="local",
            conversation_id=None,
            idempotent=False,
            state=StepState.EXECUTING,
        )
    )


def seed_unbound(*, state: str = "executing", include_progress: bool = True) -> None:
    runs_path, progress_path = paths()
    os.makedirs(os.path.dirname(runs_path), exist_ok=True)
    run = sqlite3.connect(runs_path)
    run.execute(
        "CREATE TABLE agent_runs ("
        "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    payload = {
        "id": "legacy-run",
        "state": "running",
        "current_step": 0,
        "steps": [step_payload(state)],
    }
    run.execute(
        "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
        ("legacy-run", "running", json.dumps(payload, sort_keys=True), 1.0),
    )
    run.commit()
    run.close()

    if include_progress:
        progress = sqlite3.connect(progress_path)
        progress.execute(authority_pair.PROGRESS_TABLE_SQL)
        progress.execute(
            "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) "
            "VALUES(?,?,?,?)",
            (
                "legacy-run",
                0,
                execution_step_sha256(),
                1.0,
            ),
        )
        progress.commit()
        progress.close()


def wipe() -> None:
    runs_path, progress_path = paths()
    for path in (runs_path, progress_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


runs_path, progress_path = paths()

# Adoption must never happen implicitly or without the operator asserting the
# stopped-appliance boundary.
seed_unbound()
try:
    adopt_current_pair()
    check(False, "adoption: explicit offline confirmation is mandatory")
except RuntimeError:
    check(True, "adoption: explicit offline confirmation is mandatory")
check(
    authority_pair.read_binding_path(runs_path)[0] is None
    and authority_pair.read_binding_path(progress_path)[0] is None,
    "adoption: missing confirmation writes no pair metadata",
)

pair_id = adopt_current_pair(offline_confirmed=True)
check(isinstance(pair_id, str), "adoption: coherent legacy authority receives a pair id")
check(
    authority_pair.read_binding_path(runs_path)[0]
    == (pair_id, authority_pair.RUNS_ROLE)
    and authority_pair.read_binding_path(progress_path)[0]
    == (pair_id, authority_pair.PROGRESS_ROLE),
    "adoption: both stores receive the same id with exact roles",
)
check(
    adopt_current_pair(offline_confirmed=True) == pair_id,
    "adoption: repeating the offline transition is idempotent",
)

archive = backup.create(os.path.join(_root, "backups"))
manifest = backup._read_manifest(archive)
check(manifest["schema"] == 5, "adoption: adopted legacy authority exports as schema 5")
check(
    manifest[backup.AGENT3_PAIR_MANIFEST_KEY] == pair_id,
    "adoption: exported schema-5 archive retains the adopted pair id",
)
check(backup.verify(archive)["ok"], "adoption: exported adopted pair verifies")

# The paired snapshot boundary must be monotone in the replay-safe direction.
# Start with a coherent pair whose non-idempotent step is still PENDING and has
# no execution watermark. Immediately after the first *physical* SQLite copy,
# simulate execution crossing the boundary: the live run becomes EXECUTING and
# the durable watermark appears. Runs-first snapshotting leaves the staged run
# at PENDING but captures the newer watermark, so the existing semantic check
# must refuse the backup. Progress-first would instead lose the only watermark
# and could publish an apparently coherent, replayable archive.
wipe()
seed_unbound(state="pending", include_progress=False)
progress = sqlite3.connect(progress_path)
progress.execute(authority_pair.PROGRESS_TABLE_SQL)
progress.commit()
progress.close()
race_pair_id = adopt_current_pair(offline_confirmed=True)
check(isinstance(race_pair_id, str), "snapshot race: pending pair is explicitly adopted")

physical_snapshots: list[tuple[str, str]] = []
real_snapshot = backup._original_sqlite_snapshot
race_dir = os.path.join(_root, "snapshot-crossing-race")


def crossing_snapshot(source: str, destination: str) -> None:
    physical_snapshots.append((source, destination))
    real_snapshot(source, destination)
    if len(physical_snapshots) != 1:
        return

    progress = sqlite3.connect(progress_path)
    progress.execute(
        "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) "
        "VALUES(?,?,?,?)",
        ("legacy-run", 0, execution_step_sha256(), 2.0),
    )
    progress.commit()
    progress.close()

    run = sqlite3.connect(runs_path)
    raw = run.execute("SELECT payload FROM agent_runs WHERE id='legacy-run'").fetchone()[0]
    payload = json.loads(raw)
    payload["steps"][0]["state"] = "executing"
    run.execute(
        "UPDATE agent_runs SET payload=?, updated_at=? WHERE id='legacy-run'",
        (json.dumps(payload, sort_keys=True), 2.0),
    )
    run.commit()
    run.close()


backup._original_sqlite_snapshot = crossing_snapshot
race_problem = ""
try:
    backup.create(race_dir)
    check(False, "snapshot race: crossing execution cannot publish a backup")
except ValueError as exc:
    race_problem = str(exc)
    check(True, "snapshot race: crossing execution cannot publish a backup")
finally:
    backup._original_sqlite_snapshot = real_snapshot

check(
    len(physical_snapshots) == 2
    and os.path.abspath(physical_snapshots[0][0]) == os.path.abspath(runs_path)
    and os.path.abspath(physical_snapshots[1][0]) == os.path.abspath(progress_path),
    "snapshot race: physical SQLite order is runs first, progress second",
)
check(
    "non-idempotent pending" in race_problem,
    "snapshot race: staged semantic validation names the replay-risk relation",
)
check(
    os.path.isdir(race_dir) and not os.listdir(race_dir),
    "snapshot race: refused crossing leaves no archive or temp publication",
)

# Same-pair semantic inconsistency must be refused before any provenance row is
# written. PENDING + non-idempotent with an existing execution watermark is the
# replay-risk shape the schema-5 validator is designed to reject.
wipe()
seed_unbound(state="pending")
try:
    adopt_current_pair(offline_confirmed=True)
    check(False, "adoption: stale non-idempotent run state is refused")
except RuntimeError:
    check(True, "adoption: stale non-idempotent run state is refused")
check(
    authority_pair.read_binding_path(runs_path)[0] is None
    and authority_pair.read_binding_path(progress_path)[0] is None,
    "adoption: semantic refusal commits no pair metadata",
)

# One-sided provenance is corruption, not a migration opportunity. The operator
# must not fill in the other side and thereby hide how the state was assembled.
wipe()
seed_unbound()
one_sided_id = str(uuid.uuid4())
con = sqlite3.connect(runs_path)
con.execute(authority_pair.PAIR_TABLE_SQL)
con.execute(
    f"INSERT INTO {authority_pair.PAIR_TABLE}(pair_id,store_role) VALUES(?,?)",
    (one_sided_id, authority_pair.RUNS_ROLE),
)
con.commit()
con.close()
try:
    adopt_current_pair(offline_confirmed=True)
    check(False, "adoption: one-sided pair binding is refused")
except RuntimeError:
    check(True, "adoption: one-sided pair binding is refused")
check(
    authority_pair.read_binding_path(progress_path)[0] is None,
    "adoption: one-sided refusal never repairs the missing binding",
)

# A non-empty run store without progress authority is also unadoptable.
wipe()
seed_unbound(include_progress=False)
try:
    adopt_current_pair(offline_confirmed=True)
    check(False, "adoption: non-empty run-only legacy authority is refused")
except RuntimeError:
    check(True, "adoption: non-empty run-only legacy authority is refused")

# A genuinely empty run-only store has crossed no execution boundary and needs
# no provenance transition yet.
wipe()
os.makedirs(os.path.dirname(runs_path), exist_ok=True)
con = sqlite3.connect(runs_path)
con.execute(
    "CREATE TABLE agent_runs ("
    "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
)
con.commit()
con.close()
check(
    adopt_current_pair(offline_confirmed=True) is None,
    "adoption: empty run-only store remains a safe no-op",
)
check(
    not os.path.exists(progress_path),
    "adoption: empty run-only no-op does not manufacture progress authority",
)

# Direct schema-5 entry points must be safe in a fresh interpreter without the
# public app.backup facade ever being imported. The first process proves a
# hostile run trigger is rejected by direct create().
direct_root = os.path.join(_root, "direct-schema5")
direct_env = os.environ.copy()
direct_env["KALIV_DATA_DIR"] = os.path.join(direct_root, "data")
direct_env["KALIV_AGENT3_DB"] = os.path.join(direct_root, "live", "agent3.db")
direct_env["KALIV_TOOLS_DIR"] = os.path.join(direct_root, "notes")
direct_schema_script = r'''
import os
import sqlite3
from app import backup_schema5 as backup

runs = os.environ["KALIV_AGENT3_DB"]
os.makedirs(os.path.dirname(runs), exist_ok=True)
con = sqlite3.connect(runs)
con.execute("CREATE TABLE agent_runs (id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)")
con.execute("CREATE TRIGGER hostile_run_trigger AFTER UPDATE ON agent_runs BEGIN DELETE FROM agent_runs WHERE id=NEW.id; END")
con.commit()
con.close()
try:
    backup.create(os.path.join(os.path.dirname(runs), "out"))
except ValueError as exc:
    if "canonical closed authority schema" not in str(exc):
        raise
else:
    raise SystemExit("direct schema5 create accepted hostile run trigger")
'''
direct_schema = subprocess.run(
    [sys.executable, "-c", direct_schema_script],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env=direct_env,
    capture_output=True,
    text=True,
)
check(
    direct_schema.returncode == 0,
    "direct schema5: fresh create rejects hostile closed-run-schema drift",
)
if direct_schema.returncode != 0:
    print(direct_schema.stdout)
    print(direct_schema.stderr)

# The second fresh process proves direct restore takes the runtime/restore lease
# before publishing either authority member. A live shared runtime lease must
# make forced restore fail without changing the run/progress bytes.
direct_restore_root = os.path.join(_root, "direct-schema5-restore")
direct_restore_env = os.environ.copy()
direct_restore_env["KALIV_DATA_DIR"] = os.path.join(direct_restore_root, "data")
direct_restore_env["KALIV_AGENT3_DB"] = os.path.join(
    direct_restore_root, "live", "agent3.db"
)
direct_restore_env["KALIV_TOOLS_DIR"] = os.path.join(direct_restore_root, "notes")
direct_restore_script = r'''
import hashlib
import os
from app import backup_schema5 as backup
from app.agent3.authority_pair import ensure_live_pair
from app.agent3.runtime_restore_guard import acquire_agent3_runtime_lease

runs = os.environ["KALIV_AGENT3_DB"]
ensure_live_pair(runs)
archive = backup.create(os.path.join(os.path.dirname(runs), "backups"))
progress = runs + ".execution-progress"
def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
before = (digest(runs), digest(progress))
lease = acquire_agent3_runtime_lease(runs)
try:
    try:
        backup.restore(archive, force=True)
    except RuntimeError as exc:
        if "runtime" not in str(exc).lower():
            raise
    else:
        raise SystemExit("direct schema5 restore bypassed active runtime lease")
finally:
    lease.close()
after = (digest(runs), digest(progress))
if after != before:
    raise SystemExit("blocked direct schema5 restore changed authority files")
'''
direct_restore = subprocess.run(
    [sys.executable, "-c", direct_restore_script],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env=direct_restore_env,
    capture_output=True,
    text=True,
)
check(
    direct_restore.returncode == 0,
    "direct schema5: fresh restore is excluded by an active runtime lease",
)
if direct_restore.returncode != 0:
    print(direct_restore.stdout)
    print(direct_restore.stderr)

# Directory manifests are archive-controlled input. Hash correctness must not
# authorize a path outside the configured directory root.
for safe_rel in ("nested/note.txt", r"nested\note.txt"):
    safe_parts, safe_problem = backup_schema5._directory_rel_parts(safe_rel)
    check(
        safe_problem is None and safe_parts == ("nested", "note.txt"),
        f"directory path: supported nested path stays portable ({safe_rel!r})",
    )

for unsafe_rel in (
    "",
    ".",
    "..",
    "../escape.txt",
    r"..\escape.txt",
    "/absolute.txt",
    r"\rooted.txt",
    r"C:\escape.txt",
    r"C:escape.txt",
    "bad\x00name.txt",
):
    _parts, unsafe_problem = backup_schema5._directory_rel_parts(unsafe_rel)
    check(
        unsafe_problem is not None,
        f"directory path: unsafe archive path is rejected ({unsafe_rel!r})",
    )

traversal_archive = os.path.join(_root, "directory-path-traversal.tar.gz")
traversal_rel = "../escape.txt"
traversal_payload = b"must-not-escape-notes-root"
traversal_manifest = {
    "schema": backup_schema5.BACKUP_SCHEMA,
    "created": "adversarial",
    "files": {
        "notes": {
            "kind": "dir",
            "files": {
                traversal_rel: hashlib.sha256(traversal_payload).hexdigest(),
            },
        },
    },
}
with tarfile.open(traversal_archive, "w:gz") as tar:
    member = tarfile.TarInfo(f"data/notes/{traversal_rel}")
    member.size = len(traversal_payload)
    tar.addfile(member, io.BytesIO(traversal_payload))
    manifest_bytes = json.dumps(traversal_manifest, sort_keys=True).encode("utf-8")
    manifest_member = tarfile.TarInfo("manifest.json")
    manifest_member.size = len(manifest_bytes)
    tar.addfile(manifest_member, io.BytesIO(manifest_bytes))

traversal_verify = backup_schema5.verify(traversal_archive)
check(
    not traversal_verify["ok"]
    and any("invalid directory path" in problem for problem in traversal_verify["problems"]),
    "directory path: hash-consistent traversal archive fails verification",
)
escape_path = os.path.abspath(
    os.path.join(os.environ["KALIV_TOOLS_DIR"], traversal_rel)
)
try:
    backup_schema5.restore(traversal_archive, force=True)
    check(False, "directory path: traversal archive is refused before restore")
except ValueError:
    check(True, "directory path: traversal archive is refused before restore")
check(
    not os.path.exists(escape_path),
    "directory path: refused traversal writes nothing outside notes root",
)

symlink_root = os.environ["KALIV_TOOLS_DIR"]
os.makedirs(symlink_root, exist_ok=True)
outside_root = os.path.join(_root, "outside-notes")
os.makedirs(outside_root, exist_ok=True)
link_path = os.path.join(symlink_root, "outside-link")
try:
    os.symlink(outside_root, link_path, target_is_directory=True)
except (OSError, NotImplementedError):
    check(True, "directory path: symlink containment probe unavailable on this host")
else:
    _destination, symlink_problem = backup_schema5._contained_directory_destination(
        symlink_root, "outside-link/escape.txt"
    )
    check(
        symlink_problem is not None,
        "directory path: existing parent symlink cannot escape restore root",
     )
    os.unlink(link_path)

# The Windows migration operator must establish the stopped boundary before the
# trust transition, and adoption must occur before schema-5 backup creation.
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
operator = os.path.join(repo_root, "scripts", "migrate-new-rig-state.ps1")
text = open(operator, "r", encoding="utf-8-sig").read()
main_region = text[text.index("$resolvedRuntime = $null") :]
stop_pos = main_region.index("    Save-TaskStatesAndStop")
adopt_pos = main_region.index('Write-Step "Adopting legacy Agent3 pair authority')
create_pos = main_region.index('Invoke-BackupModule -Arguments @(\"create\"')
check(
    stop_pos < adopt_pos < create_pos,
    "migration: actual appliance-stop call precedes adoption, which precedes backup create",
)
check(
    '-Module "app.agent3.adopt_pair"' in main_region
    and '@("--offline-confirmed")' in main_region,
    "migration: adoption is explicit and carries offline confirmation",
)

wipe()
shutil.rmtree(_root, ignore_errors=True)
print(f"\n===== AGENT3 PAIR ADOPTION: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
