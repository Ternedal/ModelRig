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


wizard_path = ROOT / "scripts" / "stage_a_one_click.py"
cleanup_path = ROOT / "scripts" / "stage_a_resume_cleanup.py"
stack_path = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
cmd_path = ROOT / "START_STAGE_A_TEST.cmd"
runbook_path = ROOT / "STAGED_PHYSICAL_PROMOTION.md"
ignore_path = ROOT / ".gitignore"

for path, label in (
    (wizard_path, "one-click wizard"),
    (cleanup_path, "resume helper"),
    (stack_path, "exact-head stack launcher"),
    (cmd_path, "double-click entrypoint"),
):
    check(path.is_file(), f"{label} exists")

wizard_text = wizard_path.read_text(encoding="utf-8")
stack_text = stack_path.read_text(encoding="utf-8")
cmd_text = cmd_path.read_text(encoding="utf-8")
runbook = runbook_path.read_text(encoding="utf-8")
ignore_text = ignore_path.read_text(encoding="utf-8")

check("stage_a_resume_cleanup.py" in cmd_text, "entrypoint repairs a failed resume first")
check("stage_a_one_click.py" in cmd_text, "entrypoint launches the tested wizard")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "entrypoint suppresses Python bytecode")
check("START_STAGE_A_TEST.cmd" in runbook, "runbook recommends the one-click path")

flow = (
    'strict_stage("Prepare", sha)',
    'run_preflight(planner)',
    'run_voice(planner)',
    'run_scheduler(planner, state)',
    'strict_stage("Verify", sha)',
    'strict_stage("Complete", sha, url)',
)
check(all(item in wizard_text for item in flow), "wizard contains the complete Stage A flow")
check(
    [wizard_text.index(item) for item in flow]
    == sorted(wizard_text.index(item) for item in flow),
    "Stage A steps remain in the required order",
)

check('git("pull", "--ff-only"' in wizard_text, "candidate update is fast-forward-only")
check("getpass.getpass" in wizard_text, "device token is read without echo")
check('os.environ["GH_TOKEN"]' in wizard_text, "GitHub token remains process-local")
check('state.get("candidate_sha") == sha' in wizard_text, "resume state is exact-SHA bound")
check('[ollama, "stop", planner]' in wizard_text, "voice model is unloaded before cold start")
check("worker_only=True" in wizard_text, "voice and recovery use worker-only restart")
check("-WorkerOnly" in stack_text, "stack launcher supports worker-only restart")
check("PYTHONDONTWRITEBYTECODE=1" in stack_text, "started worker cannot create local bytecode")
check("Wait-PortFree" in stack_text, "launcher waits for old local windows to close")

for ignored in (
    "/validation/stage-a-easy-state.json",
    "/validation/stage-a-runtime/",
    "/validation/archive/",
    "/validation/scheduler-pilot-latest.json",
    "/validation/scheduler-manual-observations.json",
):
    check(ignored in ignore_text, f"local artifact is ignored: {ignored}")

wizard = load("stage_a_one_click_contract", wizard_path)
check(wizard.BRANCH == "agent/t032-integration-candidate", "wizard is pinned to the candidate branch")
check(wizard.VERSION == "1.58.141", "wizard is pinned to version 1.58.141")
check(
    wizard.PROOFS == ("preflight", "agent3", "model_eval", "voice", "rag", "scheduler_pilot"),
    "wizard uses the exact six-proof allowlist",
)

calls: list[list[str]] = []
original_run = wizard.run
wizard.run = lambda args, **kwargs: calls.append(list(args))
try:
    wizard.strict_stage("Prepare", "a" * 40)
    wizard.strict_stage("Complete", "a" * 40, "https://example.com/")
finally:
    wizard.run = original_run
check(calls[0][-4:] == ["-Action", "Prepare", "-ExpectedSha", "a" * 40], "Prepare delegates exact SHA")
check(calls[1][-2:] == ["-Url", "https://example.com/"], "Complete delegates exact URL")

print(f"one-click Stage A contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
