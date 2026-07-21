#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wizard_path = ROOT / "scripts" / "scheduler_pilot_one_click.py"
stack_path = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
cmd_path = ROOT / "START_SCHEDULER_PILOT.cmd"
ignore_path = ROOT / ".gitignore"

for path, label in (
    (wizard_path, "scheduler-only wizard"),
    (stack_path, "exact-head stack launcher"),
    (cmd_path, "double-click entrypoint"),
):
    check(path.is_file(), f"{label} exists")

wizard_text = wizard_path.read_text(encoding="utf-8")
stack_text = stack_path.read_text(encoding="utf-8")
cmd_text = cmd_path.read_text(encoding="utf-8")
ignore_text = ignore_path.read_text(encoding="utf-8")

check("scheduler_pilot_one_click.py" in cmd_text, "entrypoint launches only the scheduler wizard")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "entrypoint suppresses Python bytecode")
check("stage.run_scheduler(planner, state)" in wizard_text, "wizard reuses the canonical pilot flow")
check("stage.start_stack = start_pilot_stack" in wizard_text, "crash restart keeps pilot mode")
check('"-SchedulerPilot"' in wizard_text, "every pilot stack launch requests scheduler mode")
check("[switch]$SchedulerPilot" in stack_text, "stack exposes an explicit pilot switch")
check('KALIV_SCHEDULER=1' in stack_text, "pilot worker enables the scheduler")
check('KALIV_SCHEDULER_API=1' in stack_text, "pilot stack enables the scheduler API")
check('KALIV_SCHEDULER_POLL_S=5' in stack_text, "pilot uses the bounded five-second poll")
check(
    "/validation/scheduler-pilot-easy-state.json" in ignore_text,
    "local resume state cannot dirty the candidate",
)

wizard = load("scheduler_pilot_one_click_contract", wizard_path)
check(
    wizard.BRANCH == "agent/t019-physical-pilot-candidate",
    "wizard is pinned to the isolated pilot branch",
)
check(wizard.VERSION == "1.58.141", "wizard is pinned to version 1.58.141")
check(
    wizard.report_passes(
        {"candidate": {"git_sha": "a" * 40}, "pilot": {"passed": True}},
        "a" * 40,
    ),
    "a passing report is accepted only for its exact SHA",
)
check(
    not wizard.report_passes(
        {"candidate": {"git_sha": "b" * 40}, "pilot": {"passed": True}},
        "a" * 40,
    ),
    "a passing report from another SHA is rejected",
)

calls: list[list[str]] = []
original_run = wizard.stage.run
original_which = wizard.shutil.which
wizard.stage.run = lambda args, **kwargs: calls.append(list(args))
wizard.shutil.which = lambda command: f"C:/fake/{command}.exe"
try:
    wizard.start_pilot_stack("qwen3:8b")
    wizard.start_pilot_stack("qwen3:8b", worker_only=True)
finally:
    wizard.stage.run = original_run
    wizard.shutil.which = original_which
check(all("-SchedulerPilot" in call for call in calls), "normal and recovery starts keep pilot mode")
check("-WorkerOnly" not in calls[0], "first start builds backend and worker")
check("-WorkerOnly" in calls[1], "recovery restart is worker-only")

print(f"one-click scheduler pilot contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
