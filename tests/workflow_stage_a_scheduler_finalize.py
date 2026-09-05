#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_a_scheduler_finalize.py"
LAUNCHER = ROOT / "FINALIZE_STAGE_A_SCHEDULER_PILOT.cmd"

spec = importlib.util.spec_from_file_location("stage_a_scheduler_finalize_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


source = code_of(SCRIPT)
source_lower = source.lower()
launcher = code_of(LAUNCHER)
launcher_lower = launcher.lower()

identity = {
    "version": "1.58.147",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
}
report = {
    "schema": "kaliv-scheduler-pilot/v4",
    "candidate": dict(identity),
    "pilot": {"passed": True, "problems": []},
}
root = Path(tempfile.mkdtemp(prefix="stage-a-scheduler-finalize-"))
report_path = root / "scheduler-pilot.json"
report_path.write_text(json.dumps(report), encoding="utf-8")
check(module.report_passed(report_path, identity),
      "only a full authoritative report bound to the exact identity passes")
report["candidate"]["git_sha"] = "c" * 40
report_path.write_text(json.dumps(report), encoding="utf-8")
check(not module.report_passed(report_path, identity),
      "a report from another SHA is rejected")
report["candidate"]["git_sha"] = identity["git_sha"]
report["pilot"]["problems"] = ["tampered"]
report_path.write_text(json.dumps(report), encoding="utf-8")
check(not module.report_passed(report_path, identity),
      "a report with problems cannot pass")

check('state.get("read_executed") is not True' in source,
      "finalization requires the physical read checkpoint")
check('state.get("revocation_confirmed") is not True' in source,
      "finalization requires the physical revocation checkpoint")
check('state.get("crash_recovery_confirmed") is not True' in source,
      "finalization requires the physical crash-recovery checkpoint")
check('state.get("write_pending") is not True' in source,
      "finalization refuses contradictory write state")
check(
    'revocation_occ.get("status") != "released"' in source
    and 'job.get("status") != "cancelled"' in source
    and '"pauset" not in reason' in source,
    "revocation is re-read from durable occurrence and job stores",
)
check(
    'crash_occ.get("status") != "abandoned"' in source
    and 'recovery_line not in worker_log' in source,
    "crash recovery is re-read from the ledger and the same worker log",
)
check(
    'identity.get("working_tree_clean") is True' in source
    and 'identity.get("version_stamps_consistent") is True' in source
    and 'identity.get("version") == wizard.VERSION' in source,
    "the report is bound to a clean consistent exact checkout",
)
check(
    'wizard.wait_for_write(state, timeout=900.0)' in source
    and 'wizard.matches_manifest(write_view, wizard.WRITE_SPEC)' in source,
    "the finalizer waits for exactly the canonical Android-created write grant",
)
check(
    'approval_receipts' in source
    and 'not isinstance(receipts, list) or len(receipts) < 1' in source,
    "a durable device-bound approval receipt is mandatory",
)
check(
    'wizard.wait_runs(write_id, 1, timeout=150.0)' in source
    and 'wizard.write_manual(recovery_line)' in source
    and 'wizard.generate_report(read_id, write_id)' in source,
    "one real write execution precedes derived observations and authoritative evaluation",
)
check(
    source.index('wizard.generate_report(read_id, write_id)')
    < source.index('wizard.set_enabled(write_id, False)'),
    "the report snapshots the receipt revision before the write grant is paused",
)
check(
    'if not report_passed(wizard.REPORT_PATH, identity)' in source
    and '"pilot_report_passed": True' in source,
    "checkpoint success is written only after the authoritative report passes",
)
check(
    '"production_activation": False' in source
    and 'production_activation=false' in source,
    "finalization records and displays that production remains off",
)
check(
    '/api/v1/schedules/approve' not in source
    and 'approval_token' not in source
    and 'KALIV_SCHEDULER_APPROVAL_SECRET' not in source,
    "the finalizer cannot mint, copy, or derive an approval token",
)
check('input(' not in source and 'getpass' not in source,
      "no schedule ID, token, or JSON is copied back manually")
check('stage_a_scheduler_finalize.py' in launcher,
      "the root launcher invokes only the bounded finalizer")
check('eneste manuelle handling' in launcher_lower and 'android' in launcher_lower,
      "the launcher states the one unavoidable human action")
check('ingen merge, release eller produktion aktiveres' in launcher_lower,
      "the launcher states the promotion boundary")

for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
    "modelrig_admin_key",
):
    check(forbidden not in source_lower,
          f"finalizer has no forbidden promotion or admin action: {forbidden}")

print(f"Stage A scheduler-finalize contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
