#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
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
stack_path = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
cmd_path = ROOT / "START_STAGE_A_TEST.cmd"
runbook_path = ROOT / "STAGED_PHYSICAL_PROMOTION.md"
ignore_path = ROOT / ".gitignore"

check(wizard_path.is_file(), "one-click Python wizard exists")
check(stack_path.is_file(), "exact-head Windows stack launcher exists")
check(cmd_path.is_file(), "root double-click entrypoint exists")

wizard_text = wizard_path.read_text(encoding="utf-8")
stack_text = stack_path.read_text(encoding="utf-8")
cmd_text = cmd_path.read_text(encoding="utf-8")
ignore_text = ignore_path.read_text(encoding="utf-8")
runbook = runbook_path.read_text(encoding="utf-8")

check("param()" not in wizard_text, "wizard needs no command-line parameters")
check("stage_a_one_click.py" in cmd_text, "double-click entrypoint launches the tested wizard")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "entrypoint suppresses local Python bytecode")
check("START_STAGE_A_TEST.cmd" in runbook, "authoritative runbook names the easiest entrypoint")

required_flow = (
    'strict_stage("Prepare", sha)',
    'run_preflight(planner)',
    'run_voice(planner)',
    'run_scheduler(planner, state)',
    'strict_stage("Verify", sha)',
    'strict_stage("Complete", sha, url)',
)
check(all(item in wizard_text for item in required_flow), "wizard preserves the full Stage A sequence")
check(
    [wizard_text.index(item) for item in required_flow]
    == sorted(wizard_text.index(item) for item in required_flow),
    "freeze, proofs, verify and browser completion remain ordered",
)

for forbidden in (
    'git("push"',
    'git("merge"',
    'git("tag"',
    "gh release",
    "merge_pull_request",
    "update_ref",
    "production_activation=true",
):
    check(forbidden not in wizard_text, f"wizard excludes forbidden operation: {forbidden}")

check('git("pull", "--ff-only"' in wizard_text, "candidate update is fast-forward-only")
check("getpass.getpass" in wizard_text, "device token is read without echo")
check('os.environ["GH_TOKEN"]' in wizard_text, "GitHub token remains process-local")
check("archive_previous_evidence" in wizard_text, "old rolling reports are preserved before a new candidate")
check("state.get(\"candidate_sha\") == sha" in wizard_text, "resume state is bound to the exact candidate SHA")
check("ollama\", \"stop\", planner" in wizard_text, "voice flow unloads the selected model before cold start")
check("worker_only=True" in wizard_text, "voice and recovery use an exact-head worker-only restart")
check("-WorkerOnly" in stack_text, "stack launcher exposes a worker-only restart")
check("PYTHONDONTWRITEBYTECODE=1" in stack_text, "launched worker cannot dirty the checkout with bytecode")
check("taskkill" not in stack_text and "Stop-Process" not in stack_text, "launcher never kills local processes automatically")
check("Wait-PortFree" in stack_text, "launcher waits visibly for the operator to close old windows")

for ignored in (
    "/validation/stage-a-easy-state.json",
    "/validation/stage-a-runtime/",
    "/validation/archive/",
    "/validation/scheduler-pilot-latest.json",
    "/validation/scheduler-manual-observations.json",
):
    check(ignored in ignore_text, f"local one-click artifact is ignored: {ignored}")

wizard = load("stage_a_one_click_contract", wizard_path)
check(wizard.BRANCH == "agent/t032-integration-candidate", "wizard is pinned to the integration candidate branch")
check(wizard.VERSION == "1.58.141", "wizard is pinned to candidate version 1.58.141")
check(wizard.PROOFS == ("preflight", "agent3", "model_eval", "voice", "rag", "scheduler_pilot"), "wizard uses the exact six-proof allowlist")

calls: list[list[str]] = []
original_run = wizard.run
wizard.run = lambda args, **kwargs: calls.append(list(args))
try:
    wizard.strict_stage("Prepare", "a" * 40)
    wizard.strict_stage("Complete", "a" * 40, "https://example.com/")
finally:
    wizard.run = original_run
check(calls[0][-4:] == ["-Action", "Prepare", "-ExpectedSha", "a" * 40], "Prepare delegates to the strict operator with exact SHA")
check(calls[1][-2:] == ["-Url", "https://example.com/"], "Complete delegates the exact approved URL")

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    validation = root / "validation"
    validation.mkdir()
    old = validation / "rig-preflight-latest.json"
    old.write_text("{}\n", encoding="utf-8")
    old_validation, old_state_path = wizard.VALIDATION, wizard.STATE_PATH
    wizard.VALIDATION = validation
    wizard.STATE_PATH = validation / "stage-a-easy-state.json"
    state: dict[str, object] = {}
    try:
        wizard.archive_previous_evidence("b" * 40, state)
    finally:
        wizard.VALIDATION, wizard.STATE_PATH = old_validation, old_state_path
    archives = list((validation / "archive").glob("stage-a-*"))
    check(len(archives) == 1 and (archives[0] / old.name).is_file(), "candidate change archives rather than deletes prior evidence")
    saved = json.loads((validation / "stage-a-easy-state.json").read_text(encoding="utf-8"))
    check(saved.get("candidate_sha") == "b" * 40, "resume state records the exact new candidate SHA")

print(f"one-click Stage A contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
