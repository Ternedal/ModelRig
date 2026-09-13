"""Regression: schema-5 backup must reject hidden run-store SQLite authority.

Run: PYTHONPATH=worker python3 tests/worker_agent3_run_schema_guard.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile

_root = tempfile.mkdtemp(prefix="agent3-run-schema-guard-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data")
os.environ["KALIV_AGENT3_DB"] = os.path.join(_root, "live", "agent3.db")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402
from app.agent3.authority_pair import ensure_live_pair  # noqa: E402
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


def step_payload() -> dict:
    return {
        "tool": "append_note",
        "args": {"text": "closed-schema"},
        "risk": "write",
        "sensitivity": "operational",
        "egress": "local",
        "origin": "local",
        "conversation_id": None,
        "idempotent": False,
        "state": "executing",
    }


def step_digest() -> str:
    return AgentRunStore._execution_step_sha256(
        AgentStep(
            tool="append_note",
            args={"text": "closed-schema"},
            risk=RiskClass.WRITE,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.LOCAL,
            origin="local",
            conversation_id=None,
            idempotent=False,
            state=StepState.EXECUTING,
        )
    )


runs_path = next(
    item.path for item in backup.items() if item.key == backup.AGENT3_RUNS_KEY
)
progress_path = runs_path + ".execution-progress"
pair_id = ensure_live_pair(runs_path)

run = sqlite3.connect(runs_path)
payload = {
    "id": "schema-run",
    "state": "running",
    "current_step": 0,
    "steps": [step_payload()],
}
run.execute(
    "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
    ("schema-run", "running", json.dumps(payload, sort_keys=True), 1.0),
)
run.commit()
run.close()

progress = sqlite3.connect(progress_path)
progress.execute(
    "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) "
    "VALUES(?,?,?,?)",
    ("schema-run", 0, step_digest(), 1.0),
)
progress.commit()
progress.close()

clean = backup.create(os.path.join(_root, "clean"))
check(backup.verify(clean)["ok"], "run schema: canonical paired authority backs up cleanly")
check(
    backup._read_manifest(clean)[backup.AGENT3_PAIR_MANIFEST_KEY] == pair_id,
    "run schema: clean archive retains the persistent pair identity",
)

# A trigger can mutate durable run authority after a normal runtime write. It is
# therefore authority, not harmless metadata, and may not travel in a backup.
run = sqlite3.connect(runs_path)
run.execute(
    "CREATE TRIGGER erase_run_after_update AFTER UPDATE ON agent_runs "
    "BEGIN DELETE FROM agent_runs WHERE id=NEW.id; END"
)
run.commit()
run.close()

try:
    backup.create(os.path.join(_root, "triggered"))
    check(False, "run schema: hidden trigger is refused at backup create")
except ValueError as exc:
    check(
        "closed authority schema" in str(exc),
        "run schema: trigger refusal names the closed-schema boundary",
    )

problem = backup._agent3_runs_row_count_path(runs_path, pair_id=pair_id)[1]
check(
    problem is not None and "closed authority schema" in problem,
    "run schema: direct authority inspection also rejects the trigger",
)

shutil.rmtree(_root, ignore_errors=True)
print(f"\n===== AGENT3 RUN SCHEMA GUARD: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
