"""Regression contract for schema-5 legacy Agent3 pair adoption.

Run: PYTHONPATH=worker python3 tests/worker_agent3_pair_adoption.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid

_root = tempfile.mkdtemp(prefix="agent3-pair-adoption-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data")
os.environ["KALIV_AGENT3_DB"] = os.path.join(_root, "live", "agent3.db")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402
from app.agent3 import authority_pair  # noqa: E402
from app.agent3.adopt_pair import adopt_current_pair  # noqa: E402

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
                backup._execution_step_sha256(step_payload("executing")),
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
