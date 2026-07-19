#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "scheduler_pilot_evidence_tested",
    ROOT / "scripts" / "scheduler_pilot_evidence.py",
)
assert spec and spec.loader
pilot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pilot
spec.loader.exec_module(pilot)

passed = failed = 0
CANDIDATE = {
    "version": "1.58.test",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
}
RUNTIME = {
    "backend_version": CANDIDATE["version"],
    "worker_version": CANDIDATE["version"],
    "worker_code_sha256": CANDIDATE["code_sha256"],
    "worker_frozen": True,
    "scheduler_configured": True,
    "scheduler_running": True,
    "scheduler_resources_open": True,
    "scheduler_last_error": None,
}
MARKER = "scheduler-pilot-marker-2026-07-19-unique"
WRITE_ARGS = {"text": MARKER}
READ_ARGS = {}
WRITE_FP = "c" * 32


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def create_sources(root: Path) -> pilot.DataPaths:
    schedules_path = root / "kaliv-schedules.db"
    jobs_path = root / "modelrig-jobs.db"
    audit_path = root / "kaliv-audit.db"
    notes_path = root / "notes.md"

    schedules = sqlite3.connect(schedules_path)
    schedules.executescript(
        """
        CREATE TABLE schedules (
          id TEXT PRIMARY KEY, tool TEXT NOT NULL, args TEXT NOT NULL,
          cadence TEXT NOT NULL, approved_fingerprint TEXT, expires_at REAL NOT NULL,
          max_runs INTEGER NOT NULL, runs_used INTEGER NOT NULL, due_at REAL NOT NULL,
          missed INTEGER NOT NULL, enabled INTEGER NOT NULL, created REAL NOT NULL,
          revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE occurrences (
          claim_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL,
          occurrence_due_at REAL NOT NULL, status TEXT NOT NULL,
          created REAL NOT NULL, resolved REAL, job_id TEXT
        );
        CREATE TABLE approval_receipts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id TEXT NOT NULL,
          kind TEXT NOT NULL, fingerprint TEXT NOT NULL, device_id TEXT NOT NULL,
          nonce TEXT NOT NULL, issued_at INTEGER NOT NULL, consumed_at REAL NOT NULL,
          revision INTEGER NOT NULL
        );
        """
    )
    rows = [
        ("read-schedule", "rig_status", READ_ARGS, "every:60", None, 2, 2, 1),
        ("write-schedule", "note_append", WRITE_ARGS, "every:60", WRITE_FP, 1, 1, 0),
        ("revoke-schedule", "rig_status", READ_ARGS, "every:60", None, 2, 0, 0),
        ("recovery-schedule", "rig_status", READ_ARGS, "every:60", None, 2, 0, 1),
    ]
    for index, (sid, tool, args, cadence, fp, max_runs, runs_used, enabled) in enumerate(rows):
        schedules.execute(
            "INSERT INTO schedules VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                tool,
                json.dumps(args, ensure_ascii=False),
                cadence,
                fp,
                9_999_999.0,
                max_runs,
                runs_used,
                9_999_000.0 + index,
                0,
                enabled,
                1_000.0 + index,
                0,
            ),
        )
    occurrence_rows = [
        ("read-claim-1", "read-schedule", 1_100.0, "executed", 1_101.0, 1_102.0, "read-job-1"),
        ("read-claim-2", "read-schedule", 1_200.0, "executed", 1_201.0, 1_202.0, "read-job-2"),
        ("write-claim-1", "write-schedule", 1_300.0, "executed", 1_301.0, 1_302.0, "write-job-1"),
        ("revoke-claim-1", "revoke-schedule", 1_400.0, "released", 1_401.0, 1_402.0, "revoke-job-1"),
        ("recovery-claim-1", "recovery-schedule", 1_500.0, "abandoned", 1_501.0, 1_502.0, "recovery-job-1"),
    ]
    schedules.executemany("INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)", occurrence_rows)
    schedules.execute(
        "INSERT INTO approval_receipts "
        "(schedule_id,kind,fingerprint,device_id,nonce,issued_at,consumed_at,revision) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("write-schedule", "create", WRITE_FP, "pixel-6a", "single-use-nonce", 1_250, 1_251.5, 0),
    )
    schedules.commit()
    schedules.close()

    jobs = sqlite3.connect(jobs_path)
    jobs.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, "
        "detail TEXT NOT NULL, progress_completed INTEGER NOT NULL DEFAULT 0, "
        "progress_total INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0, "
        "created REAL NOT NULL, updated REAL NOT NULL)"
    )
    job_rows = [
        ("read-job-1", "schedule:rig_status", "completed", "occ=read-claim-1"),
        ("read-job-2", "schedule:rig_status", "completed", "occ=read-claim-2"),
        ("write-job-1", "schedule:note_append", "completed", "occ=write-claim-1"),
        ("revoke-job-1", "schedule:rig_status", "cancelled", "occ=revoke-claim-1; paused"),
        ("recovery-job-1", "schedule:rig_status", "failed", "occ=recovery-claim-1; abandoned"),
    ]
    for index, row in enumerate(job_rows):
        jobs.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,0,0,0,?,?)",
            (*row, 2_000.0 + index, 2_001.0 + index),
        )
    jobs.commit()
    jobs.close()

    audit = sqlite3.connect(audit_path)
    audit.execute(
        "CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "conversation_id TEXT, tool TEXT NOT NULL, args_json TEXT NOT NULL, risk TEXT NOT NULL, "
        "outcome TEXT NOT NULL, confirmation_id TEXT, result_summary TEXT, "
        "duration_ms INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT 'local')"
    )
    for claim in ("read-claim-1", "read-claim-2"):
        audit.execute(
            "INSERT INTO audit (ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,origin) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("2026-07-19T01:00:00", f"schedule:read-schedule:occ:{claim}", "rig_status", "{}", "read", "executed", None, "schedule"),
        )
    audit.execute(
        "INSERT INTO audit (ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,origin) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "2026-07-19T01:02:00",
            "schedule:write-schedule:occ:write-claim-1",
            "note_append",
            json.dumps(WRITE_ARGS),
            "write",
            "executed",
            f"schedule:{WRITE_FP[:12]}",
            "schedule",
        ),
    )
    audit.commit()
    audit.close()

    notes_path.write_text(f"\n## fixture\n{MARKER}\n", encoding="utf-8")
    return pilot.DataPaths(schedules_path, jobs_path, audit_path, notes_path)


def manifest() -> dict:
    return {
        "schema": pilot.MANIFEST_SCHEMA,
        "candidate": dict(CANDIDATE),
        "trials": {
            "read": {
                "schedule_id": "read-schedule",
                "tool": "rig_status",
                "cadence": "every:60",
                "max_runs": 2,
                "args_sha256": pilot._json_sha(READ_ARGS),
                "claim_ids": ["read-claim-1", "read-claim-2"],
            },
            "write": {
                "schedule_id": "write-schedule",
                "tool": "note_append",
                "cadence": "every:60",
                "max_runs": 1,
                "args_sha256": pilot._json_sha(WRITE_ARGS),
                "marker_sha256": pilot._sha256(MARKER.encode("utf-8")),
                "device_id": "pixel-6a",
                "claim_ids": ["write-claim-1"],
            },
            "revoke": {
                "schedule_id": "revoke-schedule",
                "claim_id": "revoke-claim-1",
            },
            "recovery": {
                "schedule_id": "recovery-schedule",
                "claim_id": "recovery-claim-1",
                "expected_status": "abandoned",
            },
        },
    }


with tempfile.TemporaryDirectory(prefix="scheduler-pilot-evidence-") as temp_dir:
    temp = Path(temp_dir)
    paths = create_sources(temp)
    good, good_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(good_exit == 0, "complete synthetic pilot passes")
    check(good["gate"]["physical_scheduler_pilot_complete"] is True,
          "green evidence marks the physical pilot complete")
    check(good["gate"]["production_activation"] is False,
          "pilot evidence cannot activate production")
    check(all(phase["passed"] for phase in good["phases"].values()),
          "all four pilot phases pass independently")
    check(good["phases"]["read"]["receipt_count"] == 0,
          "read path proves absence of a write receipt")
    check(good["phases"]["write"]["approval_receipt"]["device_id"] == "pixel-6a",
          "write path retains paired-device attribution")
    serialized = json.dumps(good, ensure_ascii=False)
    check(MARKER not in serialized, "report excludes the note marker text")
    check("single-use-nonce" not in serialized, "report hashes rather than exposes receipt nonce")
    check(str(paths.schedules.parent) not in serialized, "report excludes local database paths")

    bad_runtime = dict(RUNTIME, worker_code_sha256="d" * 64)
    mismatch, mismatch_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=bad_runtime, paths=paths, now=3_000.0
    )
    check(mismatch_exit == 1, "runtime code mismatch blocks evidence")
    check("worker code fingerprint does not match the checkout" in mismatch["gate"]["errors"],
          "runtime mismatch reason is explicit")

    notes_original = paths.notes.read_text(encoding="utf-8")
    paths.notes.write_text(notes_original + f"\n{MARKER}\n", encoding="utf-8")
    duplicate, duplicate_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(duplicate_exit == 1, "duplicate note marker blocks the pilot")
    check(any("marker count" in error for error in duplicate["phases"]["write"]["errors"]),
          "duplicate write explanation is explicit")
    paths.notes.write_text(notes_original, encoding="utf-8")

    schedules = sqlite3.connect(paths.schedules)
    schedules.execute(
        "UPDATE approval_receipts SET device_id='wrong-device' WHERE schedule_id='write-schedule'"
    )
    schedules.commit()
    schedules.close()
    wrong_device, wrong_device_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(wrong_device_exit == 1, "wrong approving device blocks the pilot")
    check(any("device mismatch" in error for error in wrong_device["phases"]["write"]["errors"]),
          "device attribution failure is explicit")

    schedules = sqlite3.connect(paths.schedules)
    schedules.execute(
        "UPDATE approval_receipts SET device_id='pixel-6a' WHERE schedule_id='write-schedule'"
    )
    schedules.commit()
    schedules.close()
    audit = sqlite3.connect(paths.audit)
    audit.execute(
        "INSERT INTO audit (ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,origin) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "2026-07-19T01:02:01",
            "schedule:write-schedule:occ:write-claim-1",
            "note_append",
            json.dumps(WRITE_ARGS),
            "write",
            "executed",
            f"schedule:{WRITE_FP[:12]}",
            "schedule",
        ),
    )
    audit.commit()
    audit.close()
    duplicate_audit, duplicate_audit_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(duplicate_audit_exit == 1, "duplicate executed audit blocks the pilot")
    check(any("exactly one executed audit" in error for error in duplicate_audit["phases"]["write"]["errors"]),
          "duplicate execution evidence is explicit")

    inventory = pilot.inventory(paths)
    inventory_text = json.dumps(inventory)
    check("note_append" in inventory_text and MARKER not in inventory_text,
          "inventory exposes ids and tools but not raw args")

    report_path = temp / "nested" / "pilot.json"
    pilot._write_json_atomic(report_path, good)
    check(json.loads(report_path.read_text(encoding="utf-8"))["schema"] == pilot.SCHEMA,
          "atomic writer preserves report")
    check(not list(report_path.parent.glob(report_path.name + ".*.tmp")),
          "atomic writer leaves no partial file")

source = (ROOT / "scripts" / "scheduler_pilot_evidence.py").read_text(encoding="utf-8")
check("mode=ro" in source and "PRAGMA query_only=ON" in source,
      "collector opens SQLite sources read-only")
check("production_activation\": False" in source,
      "collector hard-codes production activation false")

print(f"\n===== SCHEDULER PILOT EVIDENCE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
