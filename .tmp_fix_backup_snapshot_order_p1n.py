from pathlib import Path

backup_path = Path("worker/app/backup.py")
text = backup_path.read_text(encoding="utf-8")
old = '''            # A paired snapshot is created progress-first and runs-second. This
            # ordering cannot manufacture a newer watermark than the run payload
            # from ordinary live execution; both copies are then bound to the
            # same random generation so independently copied files cannot later
            # masquerade as one authority snapshot.
            if runs_exists and progress_exists:
                snapshot_id = str(uuid.uuid4())
                progress_snapshot = os.path.join(stage_dir, "progress.db")
                runs_snapshot = os.path.join(stage_dir, "runs.db")
                _sqlite_snapshot(progress.path, progress_snapshot)
                _sqlite_snapshot(runs.path, runs_snapshot)
'''
new = '''            # A paired snapshot is created runs-first and progress-second.
            # Normal execution commits the run's EXECUTING transition before its
            # independent execution-start watermark. Taking the run snapshot first
            # therefore makes the staged progress authority equal to or newer than
            # the staged run payload. If execution starts in the copy gap, restore
            # is conservatively fail-closed for a non-idempotent PENDING step rather
            # than silently losing the monotonic watermark. Both copies are then
            # bound to one random generation so independently copied files cannot
            # later masquerade as one authority snapshot.
            if runs_exists and progress_exists:
                snapshot_id = str(uuid.uuid4())
                progress_snapshot = os.path.join(stage_dir, "progress.db")
                runs_snapshot = os.path.join(stage_dir, "runs.db")
                _sqlite_snapshot(runs.path, runs_snapshot)
                _sqlite_snapshot(progress.path, progress_snapshot)
'''
if old not in text:
    raise SystemExit("snapshot-order anchor not found or already changed")
text = text.replace(old, new, 1)
backup_path.write_text(text, encoding="utf-8")

test_path = Path("tests/worker_backup_snapshot_order.py")
if test_path.exists():
    raise SystemExit("snapshot-order regression already exists")
test_path.write_text(r'''from __future__ import annotations

import os
import sqlite3
import tarfile
import tempfile

root = tempfile.mkdtemp(prefix="kaliv-backup-order-regression-")
os.environ["KALIV_DATA_DIR"] = os.path.join(root, "data")
os.environ["KALIV_AGENT3_DB"] = os.path.join(root, "agent3.db")
os.environ["MODELRIG_DATA"] = os.path.join(root, "missing-data.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(root, "missing-notes")

from app import backup  # noqa: E402
from app.agent3.core import (  # noqa: E402
    AgentRun,
    AgentRunStore,
    AgentStep,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    TurnRequest,
)

runs_path = os.environ["KALIV_AGENT3_DB"]
progress_path = runs_path + ".execution-progress"
store = AgentRunStore(runs_path)
run = AgentRun(
    id="snapshot-order-run",
    request=TurnRequest(message="backup race", mode="rig", tools=True),
    route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
    steps=[
        AgentStep(
            tool="non_idempotent_read",
            args={"value": 1},
            risk=RiskClass.READ,
            idempotent=False,
            summary="one-shot read",
        )
    ],
)
store.save_with_event(run, "run_created", {})

original_snapshot = backup._sqlite_snapshot
copy_order: list[str] = []
triggered = False


def hooked_snapshot(source: str, destination: str) -> None:
    global triggered
    original_snapshot(source, destination)
    if source in {runs_path, progress_path}:
        copy_order.append(source)
    if source == runs_path and not triggered:
        triggered = True
        live = store.load(run.id)
        assert live is not None
        expected = live.to_json()
        live.steps[0].state = StepState.EXECUTING
        assert store.save_with_event_if_unchanged(
            live,
            expected_state=RunState.RUNNING,
            expected_payload=expected,
            kind="step_started",
            payload={"step_index": 0},
        )
        marker_count = store._progress_conn.execute(
            "SELECT COUNT(*) FROM agent_execution_starts WHERE run_id=?", (run.id,)
        ).fetchone()[0]
        assert marker_count == 1, marker_count


backup._sqlite_snapshot = hooked_snapshot
try:
    archive = backup.create(os.path.join(root, "backups"))
finally:
    backup._sqlite_snapshot = original_snapshot

assert triggered, "regression did not hit the run->progress copy gap"
assert copy_order[:2] == [runs_path, progress_path], copy_order
verified = backup.verify(archive)
assert verified["ok"], verified

pair_dir = os.path.join(root, "pair")
os.makedirs(pair_dir, exist_ok=True)
pair_runs = os.path.join(pair_dir, "agent3.db")
pair_progress = pair_runs + ".execution-progress"
with tarfile.open(archive, "r:gz") as tar:
    for member, destination in (
        (f"data/{backup.AGENT3_RUNS_KEY}", pair_runs),
        (f"data/{backup.AGENT3_EXECUTION_PROGRESS_KEY}", pair_progress),
    ):
        src = tar.extractfile(member)
        assert src is not None
        with open(destination, "wb") as out:
            out.write(src.read())

con = sqlite3.connect(pair_runs)
archived_payload = con.execute(
    "SELECT payload FROM agent_runs WHERE id=?", (run.id,)
).fetchone()[0]
con.close()
archived_run = AgentRun.from_json(archived_payload)
assert archived_run.steps[0].state is StepState.PENDING, archived_run.steps[0].state

con = sqlite3.connect(pair_progress)
archived_markers = con.execute(
    "SELECT COUNT(*) FROM agent_execution_starts WHERE run_id=?", (run.id,)
).fetchone()[0]
con.close()
assert archived_markers == 1, archived_markers

# The pair intentionally represents the safe side of the cross-store race:
# run payload is older, watermark authority is newer. Recovery must therefore
# refuse a non-idempotent PENDING replay rather than lose execution evidence.
pair_store = AgentRunStore(pair_runs)
loaded = pair_store.load(run.id)
assert loaded is not None
assert loaded.steps[0].state is StepState.PENDING
assert loaded.steps[0].idempotent is False
assert pair_store.execution_progress_matches(loaded) is False
pair_store._conn.close()
pair_store._progress_conn.close()

store._conn.close()
store._progress_conn.close()
print("snapshot-order regression passed: progress authority cannot lag the staged run payload")
''', encoding="utf-8")
print("applied P1n backup snapshot ordering fix + regression")
