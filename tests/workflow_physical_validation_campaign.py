#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
    "physical_validation_campaign_test",
    SCRIPTS / "physical_validation_campaign.py",
)
preflight = load_module("rig_preflight_report_test", SCRIPTS / "rig_preflight.py")

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


NOW = datetime.now(timezone.utc).replace(microsecond=0)
CANDIDATE = {
    "version": "1.58.test",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "main",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "version_stamps_consistent": True,
    "version_check_detail": None,
}


def valid_reports() -> dict[str, dict]:
    stamp = NOW.isoformat()
    return {
        "preflight": {
            "schema": campaign.PREFLIGHT_SCHEMA,
            "generated_at": stamp,
            "candidate": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "backend": {"base_url": "http://127.0.0.1:8080"},
            "ready": True,
            "already_validated": False,
            "summary": {"checks": 2, "ok": 1, "warnings": 1, "failures": 0},
            "checks": [
                {"name": "backend", "status": "ok", "detail": "200", "fix": ""},
                {"name": "report", "status": "warn", "detail": "not yet", "fix": "run validation"},
            ],
        },
        "agent3": {
            "schema": "kaliv-agent3-rig-validation/v1",
            "started_at": (NOW - timedelta(minutes=3)).isoformat(),
            "finished_at": stamp,
            "success": True,
            "target": {
                "modelrig_version": CANDIDATE["version"],
                "worker_version": CANDIDATE["version"],
                "code_sha256": CANDIDATE["code_sha256"],
                "planner_model": "fake-local-planner",
                "write_decision": "deny",
            },
            "cleanup": {
                "deleted": True,
                "content_erased": True,
                "source_ref_erased": True,
            },
            "error": None,
        },
        "model_eval": {
            "schema": "kaliv-agent3-model-eval/v1",
            "started_at": (NOW - timedelta(minutes=2)).isoformat(),
            "finished_at": stamp,
            "target": {
                "planner_model": "fake-local-planner",
                "execution_mode": "plan-only",
                "starts_plans": False,
                "executes_tools": False,
            },
            "backend": {
                "version": CANDIDATE["version"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "summary": {
                "tasks": 40,
                "request_errors": 0,
                "exact_match_rate": 1.0,
                "discipline_rate": 1.0,
                "latency_ms": {"p50": 100.0, "p95": 200.0},
            },
        },
        "voice": {
            "schema": "kaliv-voice-baseline/v1",
            "generated_at": stamp,
            "build": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
            },
            "gate": {"passed": True},
            "summary": {
                "completed": 40,
                "errors": 0,
                "wer_micro": 0.05,
                "cer_micro": 0.02,
                "cold_probe_completed": True,
                "manual": {"provided": True, "passed": True, "trials": 5},
                "cancellation": {"probes": 4, "passed": 4, "errors": 0},
                "latency_ms": {"first_audio": {"p50": 900.0, "p95": 1300.0}},
            },
        },
        "rag": {
            "schema": "kaliv-rag-benchmark/v1",
            "generated_at": stamp,
            "build": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
            },
            "ollama": {"embedding_model": "nomic-embed-text"},
            "configuration": {"scales": [1000, 10000]},
            "scales": [
                {"scale": 1000, "cleanup": {"clean": True}},
                {"scale": 10000, "cleanup": {"clean": True}},
            ],
            "summary": {
                "errors": 0,
                "minimum_recall_at_5": 0.975,
                "maximum_query_p95_ms": 350.0,
            },
            "gate": {"passed": True},
        },
        "lifecycle": {
            "schema": campaign.LIFECYCLE_SCHEMA,
            "candidate": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "host": {"hostname": "rig", "windows_version": "Windows test"},
            "started_at": (NOW - timedelta(minutes=20)).isoformat(),
            "finished_at": stamp,
            "trials": {
                "reboot": {
                    "performed": True,
                    "ready": True,
                    "ready_ms": 65000,
                    "backend_version": CANDIDATE["version"],
                    "worker_version": CANDIDATE["version"],
                    "worker_code_sha256": CANDIDATE["code_sha256"],
                },
                "supervisor_backend": {
                    "performed": True,
                    "restarted": True,
                    "ready": True,
                    "restart_ms": 3000,
                    "active_version": CANDIDATE["version"],
                    "active_code_sha256": CANDIDATE["code_sha256"],
                },
                "supervisor_worker": {
                    "performed": True,
                    "restarted": True,
                    "ready": True,
                    "restart_ms": 4000,
                    "active_version": CANDIDATE["version"],
                    "active_code_sha256": CANDIDATE["code_sha256"],
                },
                "good_update": {
                    "performed": True,
                    "source_version": "1.57.previous",
                    "source_git_sha": "c" * 40,
                    "target_version": CANDIDATE["version"],
                    "target_git_sha": CANDIDATE["git_sha"],
                    "target_code_sha256": CANDIDATE["code_sha256"],
                    "ready": True,
                    "rollback_observed": False,
                    "data_preserved": True,
                    "schedules_preserved": True,
                },
                "bad_update": {
                    "performed": True,
                    "attempted_version": "broken",
                    "attempted_git_sha": "d" * 40,
                    "rejected_or_rolled_back": True,
                    "active_version": CANDIDATE["version"],
                    "active_git_sha": CANDIDATE["git_sha"],
                    "active_code_sha256": CANDIDATE["code_sha256"],
                    "ready": True,
                    "data_preserved": True,
                    "schedules_preserved": True,
                },
            },
        },
    }


def fake_assessor(_report, *, current_version, current_code, report_sha256):
    assert current_version == CANDIDATE["version"]
    assert current_code == CANDIDATE["code_sha256"]
    assert len(report_sha256) == 64
    return {
        "eligible_for_developer_preview": True,
        "eligible_for_write_pilot": False,
        "production_activation": False,
        "reasons": [],
    }


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
        max_age_hours=168.0,
        min_model_exact=1.0,
    )


old_candidate = campaign.candidate_identity
old_assessor = campaign._load_agent3_assessor
campaign.candidate_identity = lambda _root: dict(CANDIDATE)
campaign._load_agent3_assessor = lambda _root: fake_assessor
try:
    with tempfile.TemporaryDirectory(dir=ROOT, prefix="campaign-test-") as temp_dir:
        temp = Path(temp_dir)
        for name, report in valid_reports().items():
            write(temp / f"{name}.json", report)

        verified, verified_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(verified_exit == 0, "verify passes when every evidence file is green")
        check(verified["gate"]["physical_campaign_complete"] is True,
              "green verify marks physical campaign complete")
        check(verified["gate"]["production_activation"] is False,
              "campaign can never claim production activation")
        check(set(verified["summary"]["passed"]) == set(campaign.VALIDATORS),
              "all six evidence domains are represented")
        check(not verified["summary"]["failed"] and not verified["summary"]["missing"],
              "green verify has no hidden failure or missing evidence")

        (temp / "voice.json").unlink()
        prepared, prepare_exit = campaign.campaign_report(args_for(temp, "prepare"))
        check(prepare_exit == 0, "prepare mode accepts missing future evidence")
        check(prepared["gate"]["passed"] is True,
              "prepare gate means current candidate and present evidence are coherent")
        check(prepared["gate"]["physical_campaign_complete"] is False,
              "prepare mode never calls an incomplete campaign complete")
        check(prepared["summary"]["missing"] == ["voice"],
              "prepare report identifies the exact missing phase")

        incomplete, incomplete_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(incomplete_exit == 1, "verify blocks when one evidence file is missing")
        check(incomplete["gate"]["passed"] is False,
              "missing evidence fails the verify gate")

        voice = valid_reports()["voice"]
        voice["build"]["git_sha"] = "e" * 40
        write(temp / "voice.json", voice)
        mismatch, mismatch_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(mismatch_exit == 1, "cross-report Git SHA mismatch blocks campaign")
        check(
            any("build.git_sha mismatch" in error for error in mismatch["evidence"]["voice"]["errors"]),
            "mismatched phase explains the exact identity error",
        )

        voice = valid_reports()["voice"]
        voice["generated_at"] = (NOW - timedelta(days=20)).isoformat()
        write(temp / "voice.json", voice)
        stale, stale_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(stale_exit == 1, "stale evidence blocks campaign")
        check(stale["evidence"]["voice"]["status"] == "fail",
              "stale phase is marked failed rather than silently ignored")

        reports = valid_reports()
        reports["lifecycle"]["trials"]["reboot"]["performed"] = "true"
        write(temp / "voice.json", reports["voice"])
        write(temp / "lifecycle.json", reports["lifecycle"])
        typed, typed_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(typed_exit == 1, "string boolean cannot satisfy lifecycle evidence")
        check(
            any("reboot.performed is not true" in error for error in typed["evidence"]["lifecycle"]["errors"]),
            "lifecycle type failure is explicit",
        )
finally:
    campaign.candidate_identity = old_candidate
    campaign._load_agent3_assessor = old_assessor


# The preflight JSON output is tested without touching a rig or retaining a token.
old_env = preflight.check_env
old_backend = preflight.check_backend
old_authed = preflight.check_authed_status
old_report_state = preflight.check_report_state
old_identity = preflight._candidate_identity
old_substrate = sys.modules.get("rig_preflight_substrate")
try:
    secret = "never-persist-this-device-token"
    preflight.check_env = lambda _url: ([preflight.Check("token").ok("set")], secret)
    preflight.check_backend = lambda _url: ([preflight.Check("backend").ok("200")], True)
    preflight.check_authed_status = lambda _url, token: (
        [preflight.Check("status").ok("200")],
        {"eligible_for_developer_preview": False},
    )
    preflight.check_report_state = lambda _rig: [
        preflight.Check("report").warn("not present", "run validation")
    ]
    preflight._candidate_identity = lambda: {
        "version": CANDIDATE["version"],
        "git_sha": CANDIDATE["git_sha"],
        "code_sha256": CANDIDATE["code_sha256"],
    }
    sys.modules["rig_preflight_substrate"] = SimpleNamespace(
        check_substrate=lambda *_args: [preflight.Check("substrate").ok("ready")]
    )
    with tempfile.TemporaryDirectory(prefix="preflight-report-") as temp_dir:
        report_path = Path(temp_dir) / "preflight.json"
        exit_code = preflight.main(["--report", str(report_path)])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        check(exit_code == 0, "preflight report preserves ready exit semantics")
        check(report["schema"] == campaign.PREFLIGHT_SCHEMA,
              "preflight report uses the campaign schema")
        check(report["ready"] is True and report["summary"]["failures"] == 0,
              "preflight report derives ready from the actual checks")
        check(report["candidate"]["git_sha"] == CANDIDATE["git_sha"],
              "preflight evidence is candidate-bound")
        check(secret not in report_path.read_text(encoding="utf-8"),
              "paired-device token never reaches preflight evidence")
finally:
    preflight.check_env = old_env
    preflight.check_backend = old_backend
    preflight.check_authed_status = old_authed
    preflight.check_report_state = old_report_state
    preflight._candidate_identity = old_identity
    if old_substrate is None:
        sys.modules.pop("rig_preflight_substrate", None)
    else:
        sys.modules["rig_preflight_substrate"] = old_substrate


with tempfile.TemporaryDirectory(prefix="campaign-write-") as temp_dir:
    path = Path(temp_dir) / "nested" / "campaign.json"
    campaign._write_json_atomic(path, {"schema": campaign.SCHEMA, "value": "bevis"})
    parsed = json.loads(path.read_text(encoding="utf-8"))
    leftovers = list(path.parent.glob(path.name + ".*.tmp"))
    check(parsed["value"] == "bevis", "campaign report writer preserves UTF-8")
    check(not leftovers, "campaign report writer leaves no partial file")

source = (SCRIPTS / "physical_validation_campaign.py").read_text(encoding="utf-8")
check("urllib" not in source and "http.client" not in source,
      "campaign aggregator performs no network requests")
check("production_activation\": False" in source,
      "campaign report hard-codes production_activation=false")
check("MODELRIG_TOKEN" not in source,
      "campaign aggregator does not accept or inspect device tokens")

print(f"\n===== PHYSICAL CAMPAIGN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
