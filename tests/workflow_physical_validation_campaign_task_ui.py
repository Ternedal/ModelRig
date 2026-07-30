#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaign = load_module(
    "physical_validation_campaign_task_ui_test",
    SCRIPTS / "physical_validation_campaign.py",
)
validator = load_module(
    "physical_validation_task_ui_test",
    SCRIPTS / "physical_validation_task_ui.py",
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
CANDIDATE = {
    "version": "1.58.test",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "main",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "version_check_detail": None,
}
BINDING = {
    "pilot_report_sha256": "c" * 64,
    "pilot_candidate_git_sha": CANDIDATE["git_sha"],
    "rig_validation_report_sha256": "d" * 64,
}
RECEIPT = {
    "schema": "kaliv-agent3-capability-receipt/v1",
    "route": "rig_tools_local",
    "allowed": True,
    "blockers": [],
    "production_activation": False,
    "graph_sha256": "e" * 64,
    "plan_sha256": "f" * 64,
}


def valid_report(artifact_dir: Path) -> dict:
    clients = {}
    checks = {key: True for key in validator.REQUIRED_CLIENT_CHECKS}
    for name, platform_name in (("android", "android"), ("desktop", "windows")):
        artifact = artifact_dir / f"{name}.txt"
        artifact.write_text(f"physical {name} task UI evidence\n", encoding="utf-8")
        raw = artifact.read_bytes()
        clients[name] = {
            "platform": platform_name,
            "device": "Pixel 6a" if name == "android" else "ModelRig Windows",
            "candidate": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "selected_surface": "agent3_readonly",
            "fallback_surface": "agent2",
            "server_reason": "agent3_readonly_selected",
            "stop_terminal_state": "cancelled",
            "normal_chat_surface": "agent2",
            "checks": checks.copy(),
            "artifact": {
                "path": artifact.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            },
        }
    return {
        "schema": validator.TASK_UI_SCHEMA,
        "generated_at": NOW.isoformat(),
        "candidate": dict(CANDIDATE),
        "host": {"hostname": "rig", "platform": "Windows", "python": "3.12"},
        "configuration": {
            "base_url": "http://127.0.0.1:8080",
            "timeout_seconds": 120.0,
            "poll_interval_seconds": 0.5,
            "max_observation_age_hours": 24.0,
            "token_recorded": False,
            "production_activation": False,
        },
        "machine_probe": {
            "completed": True,
            "duration_ms": 750.0,
            "polls": 1,
            "readiness": {
                "selected_surface": "agent3_readonly",
                "fallback_surface": "agent2",
                "reason": "agent3_readonly_selected",
                "pilot_report_sha256": BINDING["pilot_report_sha256"],
                "pilot_candidate_git_sha": BINDING["pilot_candidate_git_sha"],
                "rig_validation_report_sha256": BINDING["rig_validation_report_sha256"],
                "pilot_tasks": 20,
                "pilot_successes": 20,
                "pilot_replans": 2,
                "pilot_retry_events": 0,
                "stop_fallback_proven": True,
            },
            "preview": {
                "steps": 1,
                "tools": ["rig_status"],
                "route": "rig_tools_local",
                "executed": False,
                "readiness_binding": dict(BINDING),
                "capability_receipt": dict(RECEIPT),
            },
            "run": {
                "state": "completed",
                "terminal": True,
                "steps": 1,
                "step_states": ["succeeded"],
                "event_kinds": [
                    "run_created",
                    "policy_decision",
                    "step_started",
                    "step_succeeded",
                    "run_completed",
                ],
                "answer_present": True,
                "error": None,
                "readiness_binding": dict(BINDING),
                "capability_receipt": dict(RECEIPT),
            },
            "run_id_sha256": "1" * 64,
            "message_sha256": "2" * 64,
        },
        "physical_clients": {
            "observed_at": NOW.isoformat(),
            "age_hours": 0.0,
            "operator": "Anders",
            "clients": clients,
        },
        "summary": {
            "machine_probe_completed": True,
            "android_passed": True,
            "desktop_passed": True,
            "clients": 2,
            "artifacts": 2,
        },
        "gate": {
            "passed": True,
            "production_activation": False,
            "normal_chat_route_unchanged": True,
        },
    }


def assess(report: dict) -> dict:
    result = {"errors": [], "warnings": [], "summary": {}}
    validator.validate_task_ui(
        report,
        result,
        CANDIDATE,
        {"root": ROOT},
    )
    return result


print("Physical validation campaign — T-021 task UI")
allowed = ROOT / "validation" / "agent3-task-ui-evidence"
allowed.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=allowed, prefix="campaign-task-ui-") as td:
    artifact_dir = Path(td)
    report = valid_report(artifact_dir)
    result = assess(report)
    check(not result["errors"], "valid T-021 physical report passes independent validation")
    check(
        set(result["summary"]["artifacts"]) == {"android", "desktop"},
        "campaign re-reads both physical client artifacts",
    )
    check(
        result["summary"]["terminal_state"] == "completed",
        "campaign records the completed machine-probe state",
    )

    bad = copy.deepcopy(report)
    bad["physical_clients"]["clients"]["android"]["checks"]["stop_after_fallback"] = False
    errors = assess(bad)["errors"]
    check(
        any("stop_after_fallback" in error for error in errors),
        "missing Stop-after-fallback observation blocks the gate",
    )

    bad = copy.deepcopy(report)
    bad["machine_probe"]["run"]["capability_receipt"]["plan_sha256"] = "9" * 64
    errors = assess(bad)["errors"]
    check(
        any("preview and run capability receipts differ" in error for error in errors),
        "receipt drift between preview and run blocks the gate",
    )

    bad = copy.deepcopy(report)
    bad["physical_clients"]["observed_at"] = (NOW - timedelta(hours=25)).isoformat()
    errors = assess(bad)["errors"]
    check(
        any("physical client observations" in error for error in errors),
        "stale client observation blocks the gate",
    )

    desktop_artifact = artifact_dir / "desktop.txt"
    desktop_artifact.write_text("tampered physical desktop evidence\n", encoding="utf-8")
    errors = assess(report)["errors"]
    check(
        any("desktop.artifact.sha256 does not match" in error for error in errors),
        "tampered client artifact blocks the gate independently of producer output",
    )

check(
    set(campaign.EXTENDED_VALIDATORS) == set(campaign.VALIDATORS) | {"task_ui"},
    "extended campaign adds exactly one evidence domain",
)
check(
    campaign.DEFAULT_PATHS["task_ui"].as_posix()
    == "validation/agent3-task-ui-validation-latest.json",
    "task UI rolling report has one authoritative path",
)
check(
    "agent3_task_ui_validation.py" in campaign.COMMANDS["task_ui"],
    "campaign receipt publishes the authoritative producer command",
)


def args_for(temp: Path, mode: str) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        report=temp / "campaign.json",
        preflight_report=temp / "preflight.json",
        agent3_report=temp / "agent3.json",
        model_eval_report=temp / "model_eval.json",
        voice_report=temp / "voice.json",
        rag_report=temp / "rag.json",
        lifecycle_report=temp / "lifecycle.json",
        scheduler_pilot_report=temp / "scheduler.json",
        task_ui_report=temp / "task_ui.json",
        max_age_hours=168.0,
        min_model_exact=1.0,
    )


old_candidate = campaign.candidate_identity
old_assessor = campaign._load_agent3_assessor
old_validate = campaign.validate_evidence
campaign.candidate_identity = lambda _root: dict(CANDIDATE)
campaign._load_agent3_assessor = lambda _root: (lambda *args, **kwargs: {})
try:
    with tempfile.TemporaryDirectory(prefix="campaign-task-ui-slot-") as td:
        temp = Path(td)

        def fake_validate(
            _root,
            name,
            path,
            *,
            candidate,
            thresholds,
            now,
            max_age_hours,
        ):
            present = name != "task_ui" or path.exists()
            return {
                "name": name,
                "path": str(path),
                "present": present,
                "sha256": "0" * 64 if present else None,
                "bytes": 1 if present else 0,
                "status": "pass" if present else "missing",
                "age_hours": 0.0 if present else None,
                "errors": [] if present else ["evidence file is missing"],
                "warnings": [],
                "summary": {},
            }

        campaign.validate_evidence = fake_validate
        verified, code = campaign.campaign_report(args_for(temp, "verify"))
        check(code == 1, "verify blocks when T-021 physical evidence is missing")
        check(
            verified["summary"]["missing"] == ["task_ui"],
            "verify names the missing T-021 phase exactly",
        )
        check(
            verified["summary"]["total"] == 8,
            "extended campaign contains eight physical evidence domains",
        )

        prepared, code = campaign.campaign_report(args_for(temp, "prepare"))
        check(code == 0, "prepare accepts a not-yet-run T-021 physical phase")
        check(
            prepared["gate"]["physical_campaign_complete"] is False,
            "prepare never calls missing T-021 evidence complete",
        )

        (temp / "task_ui.json").write_text("{}", encoding="utf-8")
        verified, code = campaign.campaign_report(args_for(temp, "verify"))
        check(code == 0, "verify passes once all eight domains pass")
        check(
            verified["gate"]["physical_campaign_complete"] is True,
            "all eight passing domains complete the campaign",
        )
finally:
    campaign.candidate_identity = old_candidate
    campaign._load_agent3_assessor = old_assessor
    campaign.validate_evidence = old_validate

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
