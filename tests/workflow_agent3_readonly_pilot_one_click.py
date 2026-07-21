#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_readonly_pilot_one_click.py"
CMD = ROOT / "START_AGENT3_READONLY_PILOT.cmd"
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
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("agent3_readonly_pilot_one_click_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def passing_report(module, sha: str) -> dict:
    return {
        "schema": module.SCHEMA,
        "success": True,
        "candidate": {"git_sha": sha, "version": module.VERSION},
        "target": {"production_activation": False},
        "summary": {
            "tasks": 20,
            "successes": 20,
            "failures": 0,
            "error_types": {},
        },
        "stop_fallback": {"success": True, "fallback_path": "/api/v1/chat"},
    }


check(SCRIPT.is_file(), "one-click Python operator exists")
check(CMD.is_file(), "double-click launcher exists")
cmd_text = CMD.read_text(encoding="utf-8")
script_text = SCRIPT.read_text(encoding="utf-8")
check("agent3_readonly_pilot_one_click.py" in cmd_text, "launcher invokes the one-click operator")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "launcher suppresses Python bytecode")
check("%*" not in cmd_text, "launcher accepts no free-form command arguments")
check("agent3_readonly_pilot.py" in script_text, "operator reuses the canonical 20-task harness")
check("run-agent3-rig-validation.ps1" in script_text, "operator creates fresh promotion-grade rig evidence")
check("stage.start_stack(planner)" in script_text, "operator starts the exact-head stack")
check("stage.ensure_device_token()" in script_text, "operator obtains the token through the hidden helper")

module = load_module()
check(module.BRANCH == "agent/t020-readonly-pilot-candidate-v2", "operator is pinned to the isolated T-020 parent")
check(module.VERSION == "1.58.141", "operator is pinned to candidate version 1.58.141")

sha = "a" * 40
good = passing_report(module, sha)
check(module.report_passes(good, sha), "exact-SHA 20/20 report passes")
wrong_sha = json.loads(json.dumps(good))
wrong_sha["candidate"]["git_sha"] = "b" * 40
check(not module.report_passes(wrong_sha, sha), "report from another SHA is rejected")
short = json.loads(json.dumps(good))
short["summary"]["successes"] = 19
short["summary"]["failures"] = 1
check(not module.report_passes(short, sha), "19/20 cannot pass")
activated = json.loads(json.dumps(good))
activated["target"]["production_activation"] = True
check(not module.report_passes(activated, sha), "production activation can never pass")
no_fallback = json.loads(json.dumps(good))
no_fallback["stop_fallback"]["success"] = False
check(not module.report_passes(no_fallback, sha), "missing stop/fallback evidence cannot pass")

commands: list[list[str]] = []
original_run = module.stage.run
module.stage.run = lambda args, **kwargs: (
    commands.append(list(args)) or SimpleNamespace(returncode=0)
)
os.environ["MODELRIG_TOKEN"] = "secret-token-must-not-appear"
try:
    check(module.run_pilot("qwen3:8b") == 0, "canonical harness exit code is returned")
finally:
    module.stage.run = original_run
    os.environ.pop("MODELRIG_TOKEN", None)
joined = " ".join(commands[0])
check("--token" not in joined, "device token is never passed as a CLI argument")
check("secret-token-must-not-appear" not in joined, "device token value never appears in arguments")
check(commands[0].count("qwen3:8b") == 3, "planner, answer and fallback use the selected local model")

with tempfile.TemporaryDirectory(prefix="kaliv-t020-report-") as temp:
    temp_root = Path(temp)
    original_validation = module.VALIDATION
    original_report = module.REPORT_PATH
    module.VALIDATION = temp_root / "validation"
    module.REPORT_PATH = module.VALIDATION / "agent3-readonly-pilot-latest.json"
    module.REPORT_PATH.parent.mkdir(parents=True)
    module.REPORT_PATH.write_text(json.dumps({"success": False}) + "\n", encoding="utf-8")
    try:
        module.archive_existing("failed")
        archived = list((module.VALIDATION / "archive").glob("agent3-readonly-failed-*/agent3-readonly-pilot-latest.json"))
        check(len(archived) == 1, "failed report is archived, not deleted")
        check(not module.REPORT_PATH.exists(), "rolling path is cleared after archive")
    finally:
        module.VALIDATION = original_validation
        module.REPORT_PATH = original_report

with tempfile.TemporaryDirectory(prefix="kaliv-t020-rig-") as temp:
    original_rig = module.RIG_REPORT
    original_run = module.stage.run
    module.RIG_REPORT = Path(temp) / "rig.json"
    module.RIG_REPORT.write_text(json.dumps({"schema": "evidence"}) + "\n", encoding="utf-8")
    validation_commands: list[list[str]] = []
    module.stage.run = lambda args, **kwargs: (
        validation_commands.append(list(args)) or SimpleNamespace(returncode=0)
    )
    try:
        module.run_rig_validation("qwen3:8b")
    finally:
        module.stage.run = original_run
        module.RIG_REPORT = original_rig
    validation_joined = " ".join(validation_commands[0])
    check("run-agent3-rig-validation.ps1" in validation_joined, "authoritative fail-closed validation runner is used")
    check("--token" not in validation_joined, "rig validation also keeps token out of arguments")

with tempfile.TemporaryDirectory(prefix="kaliv-t020-main-") as temp:
    temp_root = Path(temp)
    original_report = module.REPORT_PATH
    original_validation = module.VALIDATION
    original_ensure_candidate = module.stage.ensure_candidate
    original_ensure_models = module.stage.ensure_models
    original_ensure_token = module.stage.ensure_device_token
    original_start = module.stage.start_stack
    original_validation_fn = module.run_rig_validation
    original_pilot_fn = module.run_pilot
    original_heading = module.stage.heading
    original_ok = module.stage.ok
    original_note = module.stage.note
    module.VALIDATION = temp_root / "validation"
    module.REPORT_PATH = module.VALIDATION / "agent3-readonly-pilot-latest.json"
    module.REPORT_PATH.parent.mkdir(parents=True)
    order: list[str] = []
    module.stage.ensure_candidate = lambda: (order.append("candidate") or sha)
    module.stage.ensure_models = lambda: (order.append("models") or "qwen3:8b")
    module.stage.ensure_device_token = lambda: order.append("token")
    module.stage.start_stack = lambda planner: order.append("stack:" + planner)
    module.run_rig_validation = lambda planner: order.append("validation:" + planner)

    def fake_pilot(planner: str) -> int:
        order.append("pilot:" + planner)
        module.REPORT_PATH.write_text(json.dumps(passing_report(module, sha)) + "\n", encoding="utf-8")
        return 0

    module.run_pilot = fake_pilot
    module.stage.heading = lambda _text: None
    module.stage.ok = lambda _text: None
    module.stage.note = lambda _text: None
    try:
        check(module.main() == 0, "simulated one-click run succeeds")
        check(
            order == [
                "candidate",
                "models",
                "token",
                "stack:qwen3:8b",
                "validation:qwen3:8b",
                "pilot:qwen3:8b",
            ],
            "operator sequence is candidate, models, token, stack, validation, pilot",
        )
        order.clear()
        check(module.main() == 0, "existing exact-SHA success exits cleanly")
        check(order == ["candidate"], "existing success avoids models, token and stack restart")
    finally:
        module.REPORT_PATH = original_report
        module.VALIDATION = original_validation
        module.stage.ensure_candidate = original_ensure_candidate
        module.stage.ensure_models = original_ensure_models
        module.stage.ensure_device_token = original_ensure_token
        module.stage.start_stack = original_start
        module.run_rig_validation = original_validation_fn
        module.run_pilot = original_pilot_fn
        module.stage.heading = original_heading
        module.stage.ok = original_ok
        module.stage.note = original_note

for forbidden in ("merge_pull_request", "git push", "git tag", "release", "production_activation=true"):
    check(forbidden not in script_text.lower(), f"operator has no forbidden action surface: {forbidden}")

print(f"Agent 3 one-click pilot contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
