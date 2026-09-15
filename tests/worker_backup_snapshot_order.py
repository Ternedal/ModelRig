"""Regression: Agent3 paired backup snapshots must be monotone under live execution.

Run: PYTHONPATH=worker python3 tests/worker_backup_snapshot_order.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-order-test-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data-root")
os.environ["MODELRIG_DATA"] = os.path.join(_root, "backend", "modelrig-data.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402

passed = failed = 0


def check(cond: bool, name: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def member_scalar(archive: str, key: str, sql: str):
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile(f"data/{key}")
        if member is None:
            raise AssertionError(f"missing archive member {key}")
        data = member.read()
    fd, path = tempfile.mkstemp(prefix="kaliv-order-member-", suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as out:
            out.write(data)
        con = sqlite3.connect(path)
        try:
            row = con.execute(sql).fetchone()
        finally:
            con.close()
        if row is None:
            raise AssertionError(f"query returned no row for {key}: {sql}")
        return row[0] if len(row) == 1 else row
    finally:
        os.remove(path)


try:
    inventory = {item.key: item for item in backup.items()}
    runs = inventory[backup.AGENT3_RUNS_KEY]
    progress = inventory[backup.AGENT3_EXECUTION_PROGRESS_KEY]
    os.makedirs(os.path.dirname(runs.path), exist_ok=True)

    con = sqlite3.connect(runs.path)
    con.execute(
        "CREATE TABLE agent_runs ("
        "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    con.execute(
        "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
        ("race-run", "running", "before-boundary", 1.0),
    )
    con.commit()
    con.close()

    con = sqlite3.connect(progress.path)
    con.execute(
        "CREATE TABLE agent_execution_starts ("
        "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
        "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
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

        # Simulate a non-idempotent execution crossing the backup boundary after
        # the first DB snapshot: live run state advances and the independent
        # execution watermark becomes durable. The backup must preserve this in
        # the safe monotone direction: older run snapshot + newer watermark.
        run_con = sqlite3.connect(runs.path)
        run_con.execute(
            "UPDATE agent_runs SET payload=?,updated_at=? WHERE id=?",
            ("after-boundary", 2.0, "race-run"),
        )
        run_con.commit()
        run_con.close()

        progress_con = sqlite3.connect(progress.path)
        progress_con.execute(
            "INSERT INTO agent_execution_starts("
            "run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",
            ("race-run", 0, "f" * 64, 2.0),
        )
        progress_con.commit()
        progress_con.close()

    backup._sqlite_snapshot = snapshot_with_crossing_execution
    try:
        archive = backup.create(os.path.join(_root, "backups"))
    finally:
        backup._sqlite_snapshot = real_snapshot

    check(
        snapshot_sources[:2] == [os.path.abspath(runs.path), os.path.abspath(progress.path)],
        "create: paired Agent3 snapshot is runs-first then progress",
    )
    check(
        member_scalar(
            archive,
            backup.AGENT3_RUNS_KEY,
            "SELECT payload FROM agent_runs WHERE id='race-run'",
        )
        == "before-boundary",
        "race: run snapshot stays on the pre-execution side of the boundary",
    )
    check(
        member_scalar(
            archive,
            backup.AGENT3_EXECUTION_PROGRESS_KEY,
            "SELECT COUNT(*) FROM agent_execution_starts WHERE run_id='race-run'",
        )
        == 1,
        "race: later progress snapshot retains the execution watermark",
    )
    check(
        backup.verify(archive)["ok"],
        "race: monotone bound snapshot remains a valid schema-4 backup",
    )
finally:
    shutil.rmtree(_root, ignore_errors=True)

print(f"\n===== BACKUP SNAPSHOT ORDER: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
