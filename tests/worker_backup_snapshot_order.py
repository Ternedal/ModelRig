"""Regression: schema-5 Agent3 backup must fail closed across a live execution race.

Run: PYTHONPATH=worker python3 tests/worker_backup_snapshot_order.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-order-test-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data-root")
os.environ["MODELRIG_DATA"] = os.path.join(_root, "backend", "modelrig-data.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup_schema5 as backup  # noqa: E402
from app.agent3.authority_pair import ensure_live_pair  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    inventory = {item.key: item for item in backup.items()}
    runs = inventory[backup.AGENT3_RUNS_KEY]
    progress = inventory[backup.AGENT3_EXECUTION_PROGRESS_KEY]
    os.makedirs(os.path.dirname(runs.path), exist_ok=True)

    # Schema 5 requires a persistent, matched pair identity before non-empty
    # authority can be backed up. Establish it while both stores are empty.
    ensure_live_pair(runs.path)

    step = {
        "tool": "write-side-effect",
        "args": {"target": "race-proof"},
        "risk": "write",
        "sensitivity": "operational",
        "egress": "local",
        "origin": "local",
        "conversation_id": None,
        "idempotent": False,
        "state": "pending",
    }
    before_payload = {
        "id": "race-run",
        "state": "running",
        "current_step": 0,
        "steps": [step],
    }

    con = sqlite3.connect(runs.path)
    con.execute(
        "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
        ("race-run", "running", json.dumps(before_payload, sort_keys=True), 1.0),
    )
    con.commit()
    con.close()

    real_snapshot = backup._sqlite_snapshot
    snapshot_sources: list[str] = []

    def snapshot_with_crossing_execution(source: str, destination: str) -> None:
        real_snapshot(source, destination)
        snapshot_sources.append(os.path.abspath(source))
        if len(snapshot_sources) != 1:
            return

        # The runs snapshot is now fixed on pre-execution authority. Simulate the
        # real operation crossing that boundary: live run state advances and the
        # independent execution watermark becomes durable before progress is
        # snapped. A schema-5 archive must not publish this mixed generation.
        after_payload = {
            **before_payload,
            "current_step": 1,
            "steps": [{**step, "state": "succeeded"}],
        }
        run_con = sqlite3.connect(runs.path)
        run_con.execute(
            "UPDATE agent_runs SET payload=?,updated_at=? WHERE id=?",
            (json.dumps(after_payload, sort_keys=True), 2.0, "race-run"),
        )
        run_con.commit()
        run_con.close()

        progress_con = sqlite3.connect(progress.path)
        progress_con.execute(
            "INSERT INTO agent_execution_starts("
            "run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",
            ("race-run", 0, backup._execution_step_sha256(step), 2.0),
        )
        progress_con.commit()
        progress_con.close()

    backup._sqlite_snapshot = snapshot_with_crossing_execution
    backup_dir = os.path.join(_root, "backups")
    error: Exception | None = None
    try:
        backup.create(backup_dir)
    except Exception as exc:  # exact type/message asserted below
        error = exc
    finally:
        backup._sqlite_snapshot = real_snapshot

    check(
        snapshot_sources[:2] == [os.path.abspath(runs.path), os.path.abspath(progress.path)],
        "create: paired Agent3 snapshot is runs-first then progress",
    )
    check(
        isinstance(error, ValueError),
        "race: crossing execution refuses backup publication",
    )
    check(
        error is not None
        and "invalid bound Agent 3 backup snapshot" in str(error)
        and "non-idempotent pending" in str(error),
        "race: refusal is the semantic stale-run/new-watermark authority gate",
    )
    published = []
    if os.path.isdir(backup_dir):
        published = [name for name in os.listdir(backup_dir) if name.endswith(".tar.gz")]
    check(
        published == [],
        "race: no final archive is published from a mixed authority generation",
    )
finally:
    shutil.rmtree(_root, ignore_errors=True)

print(f"\n===== BACKUP SNAPSHOT ORDER: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
