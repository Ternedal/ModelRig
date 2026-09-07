#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import scripts.production_activation_gate as gate


CANDIDATE = "a" * 40
PROMOTION = "b" * 40
MAIN = "c" * 40
REPORT_SHA = "d" * 64
BODY_SHA = "e" * 64
CODE_SHA = "f" * 64
BODY_ID = "bodyid-" + "1" * 24
PACKAGE_SHA = "2" * 64


passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise AssertionError(label)
    passed += 1


def expect_error(callable_, contains: str) -> None:
    global passed
    try:
        callable_()
    except gate.ProductionActivationError as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r} in {exc!r}") from exc
        passed += 1
        return
    raise AssertionError(f"expected ProductionActivationError containing {contains!r}")


def fake_tree() -> dict:
    return {
        "promotion_git_sha": PROMOTION,
        "changed_paths": [
            "PRODUCTION_ACTIVATION.md",
            "scripts/production_activation_gate.py",
            "scripts/production_activation_promote.ps1",
            "tests/workflow_production_activation_promotion.py",
        ],
    }


def fake_body() -> dict:
    return {
        "result": {
            "schema": gate.BODYRIG_FINAL_SCHEMA,
            "production_activation": False,
            "candidate_git_sha": CANDIDATE,
            "body_id": BODY_ID,
            "package_sha256": PACKAGE_SHA,
            "machine_live_proof": True,
            "machine_quality": True,
            "product_exercise": True,
        },
        "final_receipt_sha256": BODY_SHA,
        "origin_main_sha": MAIN,
    }


def fake_agent() -> dict:
    return {
        "report_sha256": REPORT_SHA,
        "version": "2.0.13",
        "worker_code_sha256": CODE_SHA,
        "finished_at": "2026-09-07T18:00:00+00:00",
    }


with tempfile.TemporaryDirectory() as raw_tmp:
    tmp = Path(raw_tmp)
    report = tmp / "agent3.json"
    report.write_text("{}\n", encoding="utf-8")
    env = tmp / "modelrig.env"
    env.write_text(
        "MODELRIG_HOST=0.0.0.0\n"
        "KALIV_AGENT3_ENABLED=1\n"
        "KALIV_TOOLS_ENABLED=1\n"
        "KALIV_SCHEDULER=1\n"
        "KALIV_SCHEDULER_API=1\n"
        f"KALIV_AGENT3_VALIDATION_REPORT={report}\n"
        "KALIV_SCHEDULER_APPROVAL_SECRET=" + ("S" * 32) + "\n",
        encoding="utf-8",
    )

    env_result = gate._validate_target_env(env_path=env, agent3_report=report)
    check(env_result["switches"] == gate.REQUIRED_SWITCHES, "canonical production switches accepted")
    check(env_result["scheduler_approval_secret_present"] is True, "scheduler secret presence recorded without value")

    duplicate = tmp / "duplicate.env"
    duplicate.write_text(env.read_text(encoding="utf-8") + "kaliv_scheduler=1\n", encoding="utf-8")
    expect_error(
        lambda: gate._validate_target_env(env_path=duplicate, agent3_report=report),
        "duplicate target key KALIV_SCHEDULER",
    )

    scheduler_off = tmp / "scheduler-off.env"
    scheduler_off.write_text(env.read_text(encoding="utf-8").replace("KALIV_SCHEDULER=1", "KALIV_SCHEDULER=0"), encoding="utf-8")
    expect_error(
        lambda: gate._validate_target_env(env_path=scheduler_off, agent3_report=report),
        "KALIV_SCHEDULER=1",
    )

    def fake_git(repo_root: Path, *args: str) -> str:
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args and args[0] == "fetch":
            return ""
        if args == ("rev-parse", "HEAD"):
            return PROMOTION
        if args == ("rev-parse", f"origin/{gate.CANDIDATE_BRANCH}"):
            return CANDIDATE
        if args == ("rev-parse", f"origin/{gate.PROMOTION_BRANCH}"):
            return PROMOTION
        if args == ("diff", "--name-only", f"{CANDIDATE}..{PROMOTION}"):
            return "\n".join(fake_tree()["changed_paths"])
        raise AssertionError(f"unexpected git call: {args}")

    with patch.object(gate, "_git_text", side_effect=fake_git), patch.object(gate, "_git_is_ancestor", return_value=True):
        tree = gate._validate_promotion_tree(candidate_sha=CANDIDATE, repo_root=tmp)
    check(tree == fake_tree(), "promotion tree accepts only allowlisted activation tooling")

    def fake_git_bad(repo_root: Path, *args: str) -> str:
        value = fake_git(repo_root, *args)
        if args == ("diff", "--name-only", f"{CANDIDATE}..{PROMOTION}"):
            return value + "\nworker/app/agent3/api.py"
        return value

    with patch.object(gate, "_git_text", side_effect=fake_git_bad), patch.object(gate, "_git_is_ancestor", return_value=True):
        expect_error(
            lambda: gate._validate_promotion_tree(candidate_sha=CANDIDATE, repo_root=tmp),
            "non-promotion files",
        )

    def runtime_json(url: str, *, token: str | None = None, timeout: float = 5.0):
        if url.endswith("/api/v1/experimental/agent3/status"):
            return {
                "enabled": True,
                "experimental": True,
                "rig_validation": {
                    "eligible_for_write_pilot": True,
                    "production_activation": False,
                    "report_sha256": REPORT_SHA,
                },
            }
        if url.endswith("/api/v1/tools"):
            return {"tools": [{"name": "note_append"}]}
        if url.endswith("/api/v1/schedules/status"):
            return {"configured": True, "running": True, "resources_open": True, "last_error": None}
        if url.endswith("/api/v1/schedules"):
            return {"schedules": []}
        raise AssertionError(url)

    with patch.dict(os.environ, {"MODELRIG_TOKEN": "secret-token"}, clear=False), \
         patch.object(gate, "_request_ok", return_value=None), \
         patch.object(gate, "_request_json", side_effect=runtime_json):
        live = gate._validate_live_runtime(
            base_url="http://127.0.0.1:8080",
            worker_url="http://127.0.0.1:8099",
            token_env="MODELRIG_TOKEN",
            agent3_report_sha256=REPORT_SHA,
        )
    check(live["scheduler_running"] is True and live["agent3_write_pilot_eligible"] is True, "live runtime requires Agent3 + scheduler")

    def runtime_scheduler_stopped(url: str, *, token: str | None = None, timeout: float = 5.0):
        value = runtime_json(url, token=token, timeout=timeout)
        if url.endswith("/api/v1/schedules/status"):
            value = dict(value)
            value["running"] = False
        return value

    with patch.dict(os.environ, {"MODELRIG_TOKEN": "secret-token"}, clear=False), \
         patch.object(gate, "_request_ok", return_value=None), \
         patch.object(gate, "_request_json", side_effect=runtime_scheduler_stopped):
        expect_error(
            lambda: gate._validate_live_runtime(
                base_url="http://127.0.0.1:8080",
                worker_url="http://127.0.0.1:8099",
                token_env="MODELRIG_TOKEN",
                agent3_report_sha256=REPORT_SHA,
            ),
            "scheduler runner/resources",
        )

    with patch.object(gate, "_validate_promotion_tree", return_value=fake_tree()), \
         patch.object(gate, "_validate_bodyrig_evidence", return_value=fake_body()), \
         patch.object(gate, "_validate_agent3_report", return_value=fake_agent()):
        preflight = gate.build_preflight(
            candidate_sha=CANDIDATE,
            bodyrig_evidence_dir=tmp,
            agent3_report=report,
            env_file=env,
            repo_root=tmp,
        )
    check(preflight["production_activation"] is False, "preflight cannot activate production")
    check(preflight["agent3"]["write_decision"] == "approve", "preflight binds approved Agent3 write proof")

    preflight_path = tmp / "preflight.json"
    gate._write_create_only(preflight_path, preflight)
    with patch.object(gate, "_validate_promotion_tree", return_value=fake_tree()), \
         patch.object(gate, "_validate_bodyrig_evidence", return_value=fake_body()), \
         patch.object(gate, "_validate_agent3_report", return_value=fake_agent()), \
         patch.object(gate, "_validate_live_runtime", return_value={
             "backend_health": True,
             "worker_health": True,
             "agent3_enabled": True,
             "agent3_write_pilot_eligible": True,
             "tools_surface": True,
             "scheduler_configured": True,
             "scheduler_running": True,
             "scheduler_resources_open": True,
             "scheduler_admin_surface": True,
         }):
        final = gate.finalize_activation(
            candidate_sha=CANDIDATE,
            bodyrig_evidence_dir=tmp,
            agent3_report=report,
            env_file=env,
            preflight_path=preflight_path,
            base_url="http://127.0.0.1:8080",
            worker_url="http://127.0.0.1:8099",
            token_env="MODELRIG_TOKEN",
            repo_root=tmp,
        )
    check(final["production_activation"] is True, "only final live gate can emit production_activation=true")
    check(final["human_acceptance_required"] is False, "production promotion is machine-only")
    serialized = json.dumps(final, sort_keys=True)
    check("secret-token" not in serialized and ("S" * 32) not in serialized, "final receipt contains no bearer/scheduler secret")

    final_path = tmp / "production-activation.json"
    gate._write_create_only(final_path, final)
    expect_error(lambda: gate._write_create_only(final_path, final), "already exists")

print(f"===== PRODUCTION ACTIVATION PROMOTION: {passed} passed, 0 failed =====")
