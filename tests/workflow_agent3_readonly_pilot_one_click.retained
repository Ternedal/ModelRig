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
        "summary": {"tasks": 20, "successes": 20, "failures": 0, "error_types": {}},
        "stop_fallback": {"success": True, "fallback_path": "/api/v1/chat"},
    }


check(SCRIPT.is_file(), "one-click Python operator exists")
check(CMD.is_file(), "double-click launcher exists")
cmd_text = CMD.read_text(encoding="utf-8")
script_text = SCRIPT.read_text(encoding="utf-8")
check("agent3_readonly_pilot_one_click.py" in cmd_text, "launcher invokes the operator")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "launcher suppresses Python bytecode")
check("%*" not in cmd_text, "launcher accepts no free-form arguments")
check("agent3_readonly_pilot.py" in script_text, "operator reuses the canonical harness")
check("run-agent3-rig-validation.ps1" in script_text, "fresh rig validation is mandatory")
check("stage.start_stack(planner)" in script_text, "exact-head stack is started")
check("stage.ensure_device_token()" in script_text, "paired token uses the hidden helper")
check("def ensure_planner_model" in script_text, "operator owns a planner-only model selector")
check("nomic-embed-text" not in script_text, "read-only pilot never requires the embedding model")

module = load_module()
check(module.BRANCH == "agent/unified-candidate-1.58.143", "operator is pinned to the combined physical branch")
check(module.VERSION == "1.58.143", "operator is pinned to version 1.58.143")
sha = "a" * 40
good = passing_report(module, sha)
check(module.report_passes(good, sha), "exact-SHA 20/20 report passes")
for label, mutate in (
    ("wrong SHA", lambda report: report["candidate"].update(git_sha="b" * 40)),
    ("19/20", lambda report: report["summary"].update(successes=19, failures=1)),
    ("production activation", lambda report: report["target"].update(production_activation=True)),
    ("missing fallback", lambda report: report["stop_fallback"].update(success=False)),
):
    changed = json.loads(json.dumps(good))
    mutate(changed)
    check(not module.report_passes(changed, sha), f"{label} is rejected")

model_calls: list[list[str]] = []
model_saved = {
    "which": module.shutil.which,
    "request": module.stage.request_json,
    "models": module.stage.ollama_models,
    "run": module.stage.run,
    "heading": module.stage.heading,
    "ok": module.stage.ok,
    "note": module.stage.note,
}
module.shutil.which = lambda command: "C:/Ollama/ollama.exe" if command == "ollama" else None
module.stage.request_json = lambda _url: {"version": "test"}
module.stage.ollama_models = lambda: ["nomic-embed-text:latest", "qwen3:8b"]
module.stage.run = lambda args, **kwargs: model_calls.append(list(args)) or SimpleNamespace(returncode=0)
module.stage.heading = module.stage.ok = module.stage.note = lambda _text: None
try:
    check(module.ensure_planner_model() == "qwen3:8b", "existing qwen model is selected automatically")
    check(model_calls == [], "missing embedding model never triggers a pull")
finally:
    module.shutil.which = model_saved["which"]
    module.stage.request_json = model_saved["request"]
    module.stage.ollama_models = model_saved["models"]
    module.stage.run = model_saved["run"]
    module.stage.heading = model_saved["heading"]
    module.stage.ok = model_saved["ok"]
    module.stage.note = model_saved["note"]

commands: list[list[str]] = []
original_run = module.stage.run
module.stage.run = lambda args, **kwargs: commands.append(list(args)) or SimpleNamespace(returncode=0)
os.environ["MODELRIG_TOKEN"] = "secret-token-must-not-appear"
try:
    check(module.run_pilot("qwen3:8b") == 0, "canonical harness exit code is returned")
finally:
    module.stage.run = original_run
    os.environ.pop("MODELRIG_TOKEN", None)
joined = " ".join(commands[0])
check("--token" not in joined, "token is never passed as an argument")
check("secret-token-must-not-appear" not in joined, "token value never appears in arguments")
check(commands[0].count("qwen3:8b") == 3, "one local model is used for planner, answer and fallback")

with tempfile.TemporaryDirectory(prefix="kaliv-t020-report-") as temp:
    original_validation, original_report = module.VALIDATION, module.REPORT_PATH
    module.VALIDATION = Path(temp) / "validation"
    module.REPORT_PATH = module.VALIDATION / "agent3-readonly-pilot-latest.json"
    module.REPORT_PATH.parent.mkdir(parents=True)
    module.REPORT_PATH.write_text('{"success":false}\n', encoding="utf-8")
    try:
        module.archive_existing("failed")
        archived = list((module.VALIDATION / "archive").glob("agent3-readonly-failed-*/agent3-readonly-pilot-latest.json"))
        check(len(archived) == 1, "failed report is archived, not deleted")
        check(not module.REPORT_PATH.exists(), "rolling path is cleared after archive")
    finally:
        module.VALIDATION, module.REPORT_PATH = original_validation, original_report

with tempfile.TemporaryDirectory(prefix="kaliv-t020-rig-") as temp:
    original_rig, original_run = module.RIG_REPORT, module.stage.run
    module.RIG_REPORT = Path(temp) / "rig.json"
    module.RIG_REPORT.write_text('{"schema":"evidence"}\n', encoding="utf-8")
    validation_commands: list[list[str]] = []
    module.stage.run = lambda args, **kwargs: validation_commands.append(list(args)) or SimpleNamespace(returncode=0)
    try:
        module.run_rig_validation("qwen3:8b")
    finally:
        module.stage.run, module.RIG_REPORT = original_run, original_rig
    validation_args = " ".join(validation_commands[0])
    check("run-agent3-rig-validation.ps1" in validation_args, "authoritative validation runner is used")
    check("--token" not in validation_args, "rig validation keeps token out of arguments")

with tempfile.TemporaryDirectory(prefix="kaliv-t020-main-") as temp:
    saved = {
        "report": module.REPORT_PATH,
        "validation": module.VALIDATION,
        "candidate": module.stage.ensure_candidate,
        "planner": module.ensure_planner_model,
        "token": module.stage.ensure_device_token,
        "stack": module.stage.start_stack,
        "rig": module.run_rig_validation,
        "pilot": module.run_pilot,
        "heading": module.stage.heading,
        "ok": module.stage.ok,
        "note": module.stage.note,
    }
    module.VALIDATION = Path(temp) / "validation"
    module.REPORT_PATH = module.VALIDATION / "agent3-readonly-pilot-latest.json"
    module.REPORT_PATH.parent.mkdir(parents=True)
    order: list[str] = []
    module.stage.ensure_candidate = lambda: order.append("candidate") or sha
    module.ensure_planner_model = lambda: order.append("planner") or "qwen3:8b"
    module.stage.ensure_device_token = lambda: order.append("token")
    module.stage.start_stack = lambda planner: order.append("stack:" + planner)
    module.run_rig_validation = lambda planner: order.append("validation:" + planner)

    def fake_pilot(planner: str) -> int:
        order.append("pilot:" + planner)
        module.REPORT_PATH.write_text(json.dumps(passing_report(module, sha)) + "\n", encoding="utf-8")
        return 0

    module.run_pilot = fake_pilot
    module.stage.heading = module.stage.ok = module.stage.note = lambda _text: None
    try:
        check(module.main() == 0, "simulated one-click run succeeds")
        check(order == ["candidate", "planner", "token", "stack:qwen3:8b", "validation:qwen3:8b", "pilot:qwen3:8b"], "operator order is exact")
        order.clear()
        check(module.main() == 0, "existing exact-SHA success exits cleanly")
        check(order == ["candidate"], "existing success avoids model/token/stack work")
    finally:
        module.REPORT_PATH, module.VALIDATION = saved["report"], saved["validation"]
        module.stage.ensure_candidate, module.ensure_planner_model = saved["candidate"], saved["planner"]
        module.stage.ensure_device_token, module.stage.start_stack = saved["token"], saved["stack"]
        module.run_rig_validation, module.run_pilot = saved["rig"], saved["pilot"]
        module.stage.heading, module.stage.ok, module.stage.note = saved["heading"], saved["ok"], saved["note"]

for forbidden in (
    "merge_pull_request(",
    "git push",
    "git tag",
    "gh release",
    "approve_write",
    "production_activation=true",
):
    check(forbidden not in script_text.lower(), f"no forbidden action surface: {forbidden}")

print(f"Agent 3 one-click pilot contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
