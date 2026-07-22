#!/usr/bin/env python3
"""Contract for the single entrypoint covering the remaining physical pilots."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "remaining_physical_pilots.py"
CMD = ROOT / "START_REMAINING_PHYSICAL_TESTS.cmd"
AGENT = ROOT / "scripts" / "agent3_readonly_pilot_one_click.py"
SCHEDULER = ROOT / "scripts" / "scheduler_pilot_wizard.py"
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def load_module():
    spec = importlib.util.spec_from_file_location("remaining_physical_pilots_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check(SCRIPT.is_file(), "combined Python operator exists")
check(CMD.is_file(), "combined double-click launcher exists")
check(
    not (ROOT / ".github/workflows/combined-physical-pilots-compose.yml").exists(),
    "temporary composition workflow is absent",
)
check(
    not (ROOT / ".github/workflows/combined-pilot-entrypoint-finalize.yml").exists(),
    "temporary entrypoint workflow is absent",
)
source = SCRIPT.read_text(encoding="utf-8")
cmd = CMD.read_text(encoding="utf-8")
agent_source = AGENT.read_text(encoding="utf-8")
scheduler_source = SCHEDULER.read_text(encoding="utf-8")
check("remaining_physical_pilots.py" in cmd, "root launcher invokes combined operator")
check("%*" not in cmd, "launcher accepts no free-form arguments")
check("pause" in cmd.lower(), "launcher preserves visible failure output")
check(
    source.index("agent3_readonly_pilot_one_click.py")
    < source.index("scheduler_pilot_wizard.py"),
    "Agent 3 runs before scheduler to avoid stack conflicts",
)
check(
    'BRANCH = "agent/combined-physical-pilots-candidate"' in agent_source,
    "Agent 3 operator is bound to the combined branch",
)
check(
    'BRANCH = "agent/combined-physical-pilots-candidate"' in scheduler_source,
    "scheduler operator is bound to the combined branch",
)

module = load_module()
original_run = module.subprocess.run
calls: list[str] = []
module.subprocess.run = lambda args, **kwargs: calls.append(str(args[1])) or SimpleNamespace(returncode=0)
try:
    check(module.main() == 0, "simulated combined run succeeds")
finally:
    module.subprocess.run = original_run
check(calls == [str(AGENT), str(SCHEDULER)], "both pilots run once in the safe order")

calls.clear()

def fail_first(args, **kwargs):
    calls.append(str(args[1]))
    return SimpleNamespace(returncode=7)

module.subprocess.run = fail_first
try:
    check(module.main() == 7, "first pilot failure is propagated")
finally:
    module.subprocess.run = original_run
check(calls == [str(AGENT)], "scheduler is not started after Agent 3 failure")

for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
):
    check(forbidden not in source.lower(), f"combined operator has no forbidden action: {forbidden}")

print(f"Combined physical pilot contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
