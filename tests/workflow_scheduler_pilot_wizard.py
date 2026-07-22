#!/usr/bin/env python3
"""Contract for the resumable, one-click physical T-019 operator."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scheduler_pilot_wizard.py"
LAUNCHER = ROOT / "START_SCHEDULER_PILOT.cmd"

spec = importlib.util.spec_from_file_location("t019_wizard_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

passed = failed = 0


def check(value, message):
    global passed, failed
    if value:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


read = {
    "schedule_id": "read1",
    "tool": "rig_status",
    "args": {},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 3,
    "timezone": "Europe/Copenhagen",
    "misfire_policy": "run_once",
}
write = {
    "schedule_id": "write1",
    "tool": "note_append",
    "args": {"text": "pilot"},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 2,
    "timezone": "Europe/Copenhagen",
    "misfire_policy": "run_once",
}
check(module.BRANCH == "agent/combined-physical-pilots-candidate", "wizard is bound to the combined physical branch")
check(
    not (ROOT / ".github/workflows/scheduler-m2-pilot-compose.yml").exists(),
    "temporary pilot composition workflow is absent",
)
check(
    not (ROOT / ".github/workflows/scheduler-m2-pilot-time-contract.yml").exists(),
    "temporary pilot time-contract workflow is absent",
)
check(module.matches_manifest(read, module.READ_SPEC), "read manifest is exact")
check(
    not module.matches_manifest({**read, "cadence": "every:61"}, module.READ_SPEC),
    "read cadence drift is rejected",
)
check(module.matches_manifest(write, module.WRITE_SPEC), "write manifest is exact")
check(
    not module.matches_manifest(
        {**write, "args": {"text": "other"}}, module.WRITE_SPEC
    ),
    "write argument drift is rejected",
)
check(
    not module.matches_manifest(
        {**write, "timezone": "America/New_York"}, module.WRITE_SPEC
    ),
    "write timezone drift is rejected",
)
check(
    not module.matches_manifest(
        {**write, "misfire_policy": "skip"}, module.WRITE_SPEC
    ),
    "write misfire drift is rejected",
)
check(
    not module.matches_manifest({**write, "ttl_days": 2}, module.WRITE_SPEC),
    "write TTL drift is rejected",
)
check(module.schedule_view({"schedule": write}) == write, "nested API schedule is unwrapped")
check(module.schedule_id({"schedule_id": "abc"}) == "abc", "schedule id is read")

root = Path(tempfile.mkdtemp(prefix="t019-wizard-contract-"))
validation = root / "validation"
validation.mkdir()
module.REPORT_PATH = validation / "scheduler-pilot-latest.json"
module.LOG_PATH = validation / "scheduler-pilot-worker.log"
module.SCHEDULES_DB = root / "kaliv-schedules.db"
module.JOBS_DB = root / "modelrig-jobs.db"

module.REPORT_PATH.write_text(
    json.dumps({"candidate": {"git_sha": "a" * 40}, "pilot": {"passed": True}}),
    encoding="utf-8",
)
check(module.existing_report_passed("a" * 40), "passed report resumes on the same SHA")
check(not module.existing_report_passed("b" * 40), "report cannot cross SHA")

connection = sqlite3.connect(module.SCHEDULES_DB)
connection.executescript(
    """
    CREATE TABLE occurrences (
      claim_id TEXT PRIMARY KEY, schedule_id TEXT, status TEXT,
      created REAL, job_id TEXT, resolved REAL
    );
    CREATE TABLE runner_lease (
      id INTEGER PRIMARY KEY, owner_id TEXT, lease_until REAL
    );
    INSERT INTO occurrences VALUES ('old','read1','executed',1.0,'j0',2.0);
    INSERT INTO occurrences VALUES ('new','read1','reserved',3.0,NULL,NULL);
    INSERT INTO runner_lease VALUES (1,'owner',1234.5);
    """
)
connection.commit()
connection.close()
check(module.occurrence_ids("read1") == {"old", "new"}, "ledger ids are read")
check(
    module.reserved_after("read1", {"old"})["claim_id"] == "new",
    "new reserved claim is detected",
)
check(module.reserved_after("read1", {"old", "new"}) is None, "old claims are ignored")
check(module.lease_until() == 1234.5, "real owner-lease expiry is read")

connection = sqlite3.connect(module.JOBS_DB)
connection.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
connection.commit()
connection.close()
with module.lock_job_store():
    blocked = sqlite3.connect(module.JOBS_DB, timeout=0.05)
    try:
        blocked.execute("INSERT INTO jobs VALUES ('x')")
        blocked.commit()
        was_locked = False
    except sqlite3.OperationalError:
        was_locked = True
    finally:
        blocked.close()
check(was_locked, "JobStore lock creates real writer backpressure")
connection = sqlite3.connect(module.JOBS_DB)
connection.execute("INSERT INTO jobs VALUES ('ok')")
connection.commit()
connection.close()
check(True, "JobStore unlock restores writes")

line = (
    "2026 INFO app.schedule_service: scheduler: recovered 0 executed / "
    "1 abandoned / 0 unknown occurrence(s) at startup\n"
)
module.LOG_PATH.write_text(line, encoding="utf-8")
check(
    "1 abandoned" in module.wait_for_recovery_line(0, timeout=0.2),
    "recovery line is parsed from the real log shape",
)

source = SCRIPT.read_text(encoding="utf-8")
launcher = LAUNCHER.read_text(encoding="utf-8")
check("input(" not in source and "getpass" not in source, "wizard has no copy/paste prompts")
check(
    source.index("run_revocation(process, log, read_id)")
    < source.index("write_id = wait_for_write(state)"),
    "write approval happens only after long recovery phases",
)
check("scheduler_pilot_report.py" in source, "authoritative evaluator is reused")
check("git\", \"push" not in source and "git\", \"tag" not in source, "wizard has no push or tag command")
check("scheduler_pilot_wizard.py" in launcher, "root launcher invokes the wizard")
check("%~dp0" in launcher and "pause" in launcher.lower(), "launcher works by double-click and preserves failures")

print(f"\n===== T-019 WIZARD CONTRACT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
