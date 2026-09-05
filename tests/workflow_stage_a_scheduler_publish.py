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
SCRIPT = ROOT / "scripts" / "stage_a_scheduler_publish.py"
LAUNCHER = ROOT / "FINALIZE_STAGE_A_SCHEDULER_PILOT.cmd"

spec = importlib.util.spec_from_file_location("stage_a_scheduler_publish_test", SCRIPT)
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

root = Path(tempfile.mkdtemp(prefix="stage-a-scheduler-publish-"))
source_path = root / "source.json"
target_path = root / "nested" / "target.json"
payload = {"schema": "test", "value": 7}
source_path.write_text(json.dumps(payload), encoding="utf-8")
module.atomic_copy(source_path, target_path)
check(module.load_object(target_path) == payload,
      "atomic publication preserves the verified JSON object")
check(not list(target_path.parent.glob("*.tmp")),
      "atomic publication leaves no temporary file behind")

check(
    'CAMPAIGN_REPORT = ROOT / "validation" / "scheduler-pilot-latest.json"' in source
    and 'CAMPAIGN_MANUAL = ROOT / "validation" / "scheduler-manual-observations.json"' in source,
    "publication targets the authoritative Stage A campaign slots",
)
check(
    'finalizer.report_passed(report_source, identity)' in source
    and 'atomic_copy(report_source, CAMPAIGN_REPORT)' in source
    and 'finalizer.report_passed(CAMPAIGN_REPORT, identity)' in source,
    "the exact-identity report is checked before and after atomic publication",
)
check(
    'manual.get("revocation_confirmed") is not True' in source
    and '"scheduler: recovered " not in recovery_line' in source
    and 'atomic_copy(manual_source, CAMPAIGN_MANUAL)' in source,
    "derived manual evidence is validated and published with the report",
)
check(
    'data_dir.relative_to(RUNTIME.resolve())' in source
    and 'bound_dir.resolve() != data_dir' in source,
    "publication cannot escape or switch the isolated scheduler run directory",
)
check(
    'phone.get("production_activation") is not False' in source
    and 'production_activation=false' in source,
    "publication requires and displays the production-off boundary",
)
check(
    launcher.index('stage_a_scheduler_finalize.py')
    < launcher.index('stage_a_scheduler_publish.py'),
    "the root finalizer publishes only after physical finalization succeeds",
)
check('if not "%EXIT_CODE%"=="0" goto :failed' in launcher,
      "a failed finalizer or publisher cannot return success")

for forbidden in (
    "wait_for_write",
    "/api/v1/schedules/approve",
    "approval_token",
    "git push",
    "git tag",
    "gh release",
    "production_activation=true",
    "modelrig_admin_key",
):
    check(forbidden not in source_lower,
          f"publisher has no evidence-creation or promotion action: {forbidden}")

print(f"Stage A scheduler-publish contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
