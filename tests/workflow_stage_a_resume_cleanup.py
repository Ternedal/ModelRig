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


module = load("stage_a_resume_cleanup_contract", ROOT / "scripts" / "stage_a_resume_cleanup.py")

with tempfile.TemporaryDirectory() as td:
    validation = Path(td) / "validation"
    validation.mkdir()
    state_path = validation / "stage-a-easy-state.json"
    campaign_path = validation / "physical-validation-candidate-campaign-latest.json"
    failed_report = validation / "rig-preflight-latest.json"
    passing_report = validation / "rag-benchmark-latest.json"

    state_path.write_text(json.dumps({"candidate_sha": "c" * 40}), encoding="utf-8")
    campaign_path.write_text(
        json.dumps({"summary": {"failed": ["preflight"], "passed": ["rag"]}}),
        encoding="utf-8",
    )
    failed_report.write_text("failed\n", encoding="utf-8")
    passing_report.write_text("passing\n", encoding="utf-8")

    original = (module.VALIDATION, module.STATE, module.CAMPAIGN, module.PATHS, module.current_sha)
    module.VALIDATION = validation
    module.STATE = state_path
    module.CAMPAIGN = campaign_path
    module.PATHS = {"preflight": failed_report, "rag": passing_report}
    module.current_sha = lambda: "c" * 40
    try:
        code = module.main()
    finally:
        module.VALIDATION, module.STATE, module.CAMPAIGN, module.PATHS, module.current_sha = original

    archives = list((validation / "archive").glob("stage-a-failed-*"))
    check(code == 0, "resume cleanup exits successfully")
    check(len(archives) == 1, "one dated archive is created")
    check((archives[0] / failed_report.name).is_file(), "failed proof is preserved in the archive")
    check((archives[0] / campaign_path.name).is_file(), "blocking campaign receipt is preserved")
    check(passing_report.is_file(), "passing evidence remains untouched")

with tempfile.TemporaryDirectory() as td:
    validation = Path(td) / "validation"
    validation.mkdir()
    state_path = validation / "stage-a-easy-state.json"
    campaign_path = validation / "physical-validation-candidate-campaign-latest.json"
    failed_report = validation / "rig-preflight-latest.json"
    state_path.write_text(json.dumps({"candidate_sha": "d" * 40}), encoding="utf-8")
    campaign_path.write_text(json.dumps({"summary": {"failed": ["preflight"]}}), encoding="utf-8")
    failed_report.write_text("failed\n", encoding="utf-8")

    original = (module.VALIDATION, module.STATE, module.CAMPAIGN, module.PATHS, module.current_sha)
    module.VALIDATION = validation
    module.STATE = state_path
    module.CAMPAIGN = campaign_path
    module.PATHS = {"preflight": failed_report}
    module.current_sha = lambda: "e" * 40
    try:
        code = module.main()
    finally:
        module.VALIDATION, module.STATE, module.CAMPAIGN, module.PATHS, module.current_sha = original

    check(code == 0, "different-candidate cleanup is a no-op")
    check(failed_report.is_file(), "different-candidate evidence is not moved")
    check(not (validation / "archive").exists(), "no archive is created for another candidate")

print(f"Stage A resume cleanup contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
