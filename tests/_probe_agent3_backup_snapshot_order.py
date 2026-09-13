from __future__ import annotations

import os
import sqlite3
import tarfile
import tempfile

root = tempfile.mkdtemp(prefix="kaliv-backup-order-probe-")
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
    request=TurnRequest(message="probe", mode="rig", tools=True),
    route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "probe", False, True, True, False),
    steps=[
        AgentStep(
            tool="non_idempotent_read",
            args={"value": 1},
            risk=RiskClass.READ,
            idempotent=False,
            summary="probe one-shot read",
        )
    ],
)
store.save_with_event(run, "run_created", {})
pre_execution_payload = run.to_json()

original_snapshot = backup._sqlite_snapshot
triggered = False


def hooked_snapshot(source: str, destination: str) -> None:
    global triggered
    original_snapshot(source, destination)
    if source == progress_path and not triggered:
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

assert triggered, "probe did not hit the progress->run snapshot gap"
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
assert archived_run.steps[0].state is StepState.EXECUTING, archived_run.steps[0].state

con = sqlite3.connect(pair_progress)
archived_markers = con.execute(
    "SELECT COUNT(*) FROM agent_execution_starts WHERE run_id=?", (run.id,)
).fetchone()[0]
con.close()
assert archived_markers == 0, archived_markers

# The pair is generation-bound and hash-valid, yet the monotonic sidecar is
# already behind the run snapshot. The current consistency check therefore
# accepts a state that could not exist durably during normal execution.
pair_store = AgentRunStore(pair_runs)
loaded = pair_store.load(run.id)
assert loaded is not None and loaded.steps[0].state is StepState.EXECUTING
assert pair_store.execution_progress_matches(loaded) is True
pair_store._conn.close()
pair_store._progress_conn.close()

# Demonstrate why this matters: if the run payload is later rolled back to the
# pre-execution PENDING snapshot, the supposedly rollback-resistant sidecar has
# no marker left to detect the non-idempotent replay.
con = sqlite3.connect(pair_runs)
con.execute(
    "UPDATE agent_runs SET state=?, payload=? WHERE id=?",
    (RunState.RUNNING.value, pre_execution_payload, run.id),
)
con.commit()
con.close()
pair_store = AgentRunStore(pair_runs)
rolled_back = pair_store.load(run.id)
assert rolled_back is not None
assert rolled_back.steps[0].state is StepState.PENDING
assert rolled_back.steps[0].idempotent is False
assert pair_store.execution_progress_matches(rolled_back) is True
pair_store._conn.close()
pair_store._progress_conn.close()

store._conn.close()
store._progress_conn.close()
print("REPRODUCED: schema-4 backup can snapshot run authority ahead of execution-progress watermarks")
