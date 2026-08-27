#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_a_scheduler_pilot_easy.py"
RETAINED = ROOT / "scripts" / "stage_a_scheduler_pilot_easy.retained"
POWERSHELL = ROOT / "scripts" / "run-stage-a-scheduler-pilot.ps1"
LAUNCHER = ROOT / "RUN_STAGE_A_SCHEDULER_PILOT.cmd"

spec = importlib.util.spec_from_file_location("stage_a_scheduler_easy_test", SCRIPT)
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


source = SCRIPT.read_text(encoding="utf-8")
retained_source = RETAINED.read_text(encoding="utf-8")
combined_source = source + "\n" + retained_source
source_lower = combined_source.lower()
ps = POWERSHELL.read_text(encoding="utf-8")
ps_lower = ps.lower()
launcher = LAUNCHER.read_text(encoding="utf-8")
launcher_lower = launcher.lower()
main_source = retained_source[retained_source.index("def main() -> int:") :]

root = Path(tempfile.mkdtemp(prefix="stage-a-scheduler-easy-"))
state_path = root / "nested" / "state.json"
payload = {"schema": "test", "pairing_code": "123456"}
module.atomic_json(state_path, payload)
check(json.loads(state_path.read_text(encoding="utf-8")) == payload,
      "resumable state updates are atomic and valid JSON")
check(not list(state_path.parent.glob("*.tmp")),
      "atomic state updates leave no temporary file")

check(
    'CANDIDATE_BRANCH_PREFIX = "physical-proof/2.0.13"' in source
    and 'EXPECTED_VERSION = "2.0.13"' in source
    and module.CANDIDATE_BRANCH_PREFIX == "physical-proof/2.0.13"
    and module.EXPECTED_VERSION == "2.0.13"
    and 'stage-a-checkpoint-ux' not in combined_source
    and 'current != CANDIDATE_BRANCH_PREFIX' in combined_source
    and '"git", "switch"' not in combined_source
    and '"git", "fetch"' not in combined_source,
    "the easy flow binds to the exact active 2.0.13 rig candidate and never switches or fetches a branch",
)
check(
    'if stack_ready()' in retained_source
    and 'Genbruger den levende, isolerede scheduler-teststack' in retained_source,
    "a still-live isolated stack is resumed instead of replaced",
)
check(
    retained_source.index('("read-plan", ROOT / "scripts" / "stage_a_scheduler_read.py")')
    < retained_source.index('("revocation", ROOT / "scripts" / "stage_a_scheduler_revocation.py")')
    < retained_source.index('("crash-recovery", ROOT / "scripts" / "stage_a_scheduler_crash_recovery.py")'),
    "bounded physical mechanisms remain ordered read -> revoke -> recovery",
)
check(
    main_source.index("ensure_stack()")
    < main_source.index("run_bounded_steps()")
    < main_source.index("refresh_pairing()")
    < main_source.index("finalize_and_publish()")
    < main_source.index("stop_stack()"),
    "the one-click flow refreshes pairing after automation and cleans up only after publication",
)
check(
    'http://127.0.0.1:8080/api/v1/pair/start' in retained_source
    and 'state["pairing_code"] = code' in retained_source
    and 'PHONE_INSTRUCTIONS.write_text' in retained_source,
    "a fresh live pairing code is issued immediately before Android approval",
)
check(
    'run([sys.executable, str(FINALIZER)]' in retained_source
    and 'run([sys.executable, str(PUBLISHER)]' in retained_source
    and 'CAMPAIGN_REPORT.is_file()' in retained_source,
    "authoritative finalization precedes campaign publication and report existence check",
)
check(
    'Delresultater er bevaret. Lad teststacken stå' in retained_source
    and main_source.index("except (EasyPilotError, KeyboardInterrupt)")
    > main_source.index("finalize_and_publish()"),
    "a stopped run preserves the live resumable stack instead of fabricating completion",
)
check('input(' not in combined_source and 'getpass' not in combined_source,
      "no token, schedule ID, or JSON is copied into the orchestrator")

check(
    'Start-Process' in ps
    and '-Verb RunAs' in ps
    and 'Test-IsAdministrator' in ps,
    "the PowerShell entrypoint requests UAC elevation itself",
)
check(
    'git switch' not in ps
    and 'git pull' not in ps
    and 'git rev-parse HEAD' in ps
    and ps.index('git rev-parse HEAD') < ps.index('& python $pythonScript'),
    "the entrypoint binds to the checked-out candidate head without switching branches",
)
check(
    'git status --porcelain --untracked-files=no' in ps
    and "notmatch '^[0-9a-f]{40}" in ps,
    "the elevated entrypoint rejects a dirty checkout and requires a valid exact head",
)
check(
    'run-stage-a-scheduler-pilot.ps1' in launcher
    and 'en guidet scheduler-pilot' in launcher_lower,
    "the root double-click launcher invokes the elevated one-click entrypoint",
)
check(
    'din eneste handling' in launcher_lower
    and 'ingen token, id eller json' in launcher_lower,
    "the launcher describes the single operator action without technical bookkeeping",
)
check(
    'validation\\scheduler-pilot-latest.json' in launcher
    and 'ingen merge, release eller produktion' in launcher_lower,
    "the launcher names the stable report and promotion boundary",
)

for text, label in ((source_lower, "orchestrator"), (ps_lower, "entrypoint"), (launcher_lower, "launcher")):
    for forbidden in (
        "git push",
        "git tag",
        "gh release",
        "merge_pull_request",
        "production_activation=true",
        "modelrig_admin_key",
        "/api/v1/schedules/approve",
        "approval_token",
    ):
        check(forbidden not in text,
              f"{label} has no promotion or approval bypass: {forbidden}")

print(f"Stage A scheduler-easy contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
