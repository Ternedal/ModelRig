#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
        "scheduler_pilot": {
            "schema": campaign.SCHEDULER_PILOT_SCHEMA,
            "generated_at": stamp,
            "candidate": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "worker": {"base_url": "http://127.0.0.1:8099"},
            "read_schedule": {
                "schedule_id": "sched-read",
                "runs_used": 2,
                "receipts_count": 0,
            },
            "write_schedule": {
                "schedule_id": "sched-write",
                "runs_used": 1,
                "receipts_count": 1,
                "first_receipt": {
                    "kind": "create",
                    "device_id": "pixel-6a",
                    "issued_at": 1000.0,
                    "consumed_at": 1002.5,
                },
            },
            "forensics": {
                "read": {
                    "schedule": {"tool": "rig_status", "args": "{}",
                                 "cadence": "every:60", "max_runs": 3,
                                 "runs_used": 2, "revision": 1, "enabled": 0},
                    "occurrences": [
                        {"claim_id": "occ-r1", "status": "executed",
                         "occurrence_due_at": 900.0, "created": 900.0,
                         "resolved": 905.0, "job_id": "job-r1",
                         "job": {"status": "completed", "detail": "occ=occ-r1"},
                         "audit_outcomes": ["attempt", "executed"]},
                        {"claim_id": "occ-r2", "status": "released",
                         "occurrence_due_at": 960.0, "created": 960.0,
                         "resolved": 962.0, "job_id": "job-r2",
                         "job": {"status": "cancelled",
                                 "detail": "occ=occ-r2"},
                         "audit_outcomes": []},
                    ],
                    "receipts": [],
                    "window": {"first_created": 900.0,
                               "last_resolved": 962.0},
                },
                "write": {
                    "schedule": {"tool": "note_append",
                                 "args": "{\"text\": \"pilot\"}",
                                 "cadence": "every:60", "max_runs": 2,
                                 "runs_used": 1, "revision": 0, "enabled": 1},
                    "occurrences": [
                        {"claim_id": "occ-w1", "status": "executed",
                         "occurrence_due_at": 1000.0, "created": 1000.0,
                         "resolved": 1002.5, "job_id": "job-w1",
                         "job": {"status": "completed", "detail": "occ=occ-w1"},
                         "audit_outcomes": ["attempt", "executed"]},
                    ],
                    "receipts": [
                        {"kind": "create", "device_id": "pixel-6a",
                         "nonce": "n0", "issued_at": 1000,
                         "consumed_at": 1002.5, "revision": 0,
                         "fingerprint": "f" * 64},
                    ],
                    "window": {"first_created": 1000.0,
                               "last_resolved": 1002.5},
                },
            },
            "manual": {
                "revocation_confirmed": True,
                "recovery_line": ("scheduler: recovered 0 executed / 1 "
                                  "abandoned / 0 unknown occurrence(s) at "
                                  "startup"),
                "operator": "Anders",
            },
            "pilot": {"passed": True, "problems": []},
        },
    }


def reports_with_artifacts(temp: Path) -> dict[str, dict]:
    reports = valid_reports()
    for name, trial in reports["lifecycle"]["trials"].items():
        artifact = temp / f"{name}.log"
        raw = f"{name} physical lifecycle evidence\n".encode("utf-8")
        artifact.write_bytes(raw)
        trial["evidence_path"] = str(artifact.relative_to(ROOT))
        trial["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
    return reports


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
        scheduler_pilot_report=temp / "scheduler_pilot.json",
        max_age_hours=168.0,
        min_model_exact=1.0,
    )


old_candidate = campaign.candidate_identity
old_assessor = campaign._load_agent3_assessor
campaign.candidate_identity = lambda _root: dict(CANDIDATE)
campaign._load_agent3_assessor = lambda _root: fake_assessor
try:
    artifact_parent = ROOT / "validation" / "appliance-lifecycle-evidence"
    artifact_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=artifact_parent,
        prefix="campaign-test-",
    ) as temp_dir:
        temp = Path(temp_dir)
        for name, report in reports_with_artifacts(temp).items():
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

        voice = reports_with_artifacts(temp)["voice"]
        voice["build"]["git_sha"] = "e" * 40
        write(temp / "voice.json", voice)
        mismatch, mismatch_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(mismatch_exit == 1, "cross-report Git SHA mismatch blocks campaign")
        check(
            any("build.git_sha mismatch" in error for error in mismatch["evidence"]["voice"]["errors"]),
            "mismatched phase explains the exact identity error",
        )

        voice = reports_with_artifacts(temp)["voice"]
        voice["generated_at"] = (NOW - timedelta(days=20)).isoformat()
        write(temp / "voice.json", voice)
        stale, stale_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(stale_exit == 1, "stale evidence blocks campaign")
        check(stale["evidence"]["voice"]["status"] == "fail",
              "stale phase is marked failed rather than silently ignored")

        reports = reports_with_artifacts(temp)
        reports["lifecycle"]["trials"]["reboot"]["performed"] = "true"
        write(temp / "voice.json", reports["voice"])
        write(temp / "lifecycle.json", reports["lifecycle"])
        typed, typed_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(typed_exit == 1, "string boolean cannot satisfy lifecycle evidence")
        check(
            any("reboot.performed is not true" in error for error in typed["evidence"]["lifecycle"]["errors"]),
            "lifecycle type failure is explicit",
        )

        reports = reports_with_artifacts(temp)
        reports["lifecycle"]["started_at"] = (NOW + timedelta(minutes=1)).isoformat()
        write(temp / "lifecycle.json", reports["lifecycle"])
        reversed_time, reversed_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(reversed_exit == 1, "reversed lifecycle timestamps block campaign")
        check(
            "lifecycle started_at is after finished_at"
            in reversed_time["evidence"]["lifecycle"]["errors"],
            "lifecycle timestamp ordering failure is explicit",
        )

        reports = reports_with_artifacts(temp)
        reports["lifecycle"]["host"]["windows_version"] = "   "
        reports["lifecycle"]["trials"]["good_update"]["source_version"] = CANDIDATE["version"]
        reports["lifecycle"]["trials"]["good_update"]["source_git_sha"] = CANDIDATE["git_sha"]
        reports["lifecycle"]["trials"]["bad_update"]["attempted_version"] = ""
        write(temp / "lifecycle.json", reports["lifecycle"])
        metadata, metadata_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(metadata_exit == 1, "invalid lifecycle metadata blocks campaign")
        metadata_errors = metadata["evidence"]["lifecycle"]["errors"]
        check(
            "host.windows_version must be a non-empty string" in metadata_errors,
            "lifecycle host metadata is typed",
        )
        check(
            "good_update.source_version must differ from the candidate" in metadata_errors,
            "good update must prove a real version transition",
        )
        check(
            "good_update.source_git_sha must differ from the candidate" in metadata_errors,
            "good update must prove a real commit transition",
        )
        check(
            "bad_update.attempted_version must be a non-empty string" in metadata_errors,
            "bad update identifies the attempted build",
        )

        reports = reports_with_artifacts(temp)
        reboot_artifact = ROOT / reports["lifecycle"]["trials"]["reboot"]["evidence_path"]
        reboot_artifact.write_text("tampered evidence\n", encoding="utf-8")
        write(temp / "lifecycle.json", reports["lifecycle"])
        tampered, tampered_exit = campaign.campaign_report(args_for(temp, "verify"))
        check(tampered_exit == 1, "tampered lifecycle artifact blocks campaign")
        check(
            "reboot.evidence_sha256 does not match the artifact"
            in tampered["evidence"]["lifecycle"]["errors"],
            "artifact hash mismatch is explicit",
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

# --- scheduler-pilot slot: the receipt and the operator are non-negotiable ---
with tempfile.TemporaryDirectory(dir=ROOT) as td:
    temp = Path(td)
    for name, report in reports_with_artifacts(temp).items():
        write(temp / f"{name}.json", report)
    pilot = reports_with_artifacts(temp)["scheduler_pilot"]
    pilot["write_schedule"]["receipts_count"] = 0
    pilot["write_schedule"]["first_receipt"] = {}
    write(temp / "scheduler_pilot.json", pilot)
    r, code = campaign.campaign_report(args_for(temp, "verify"))
    check(code == 1, "a write pilot without its receipt fails the campaign")
    errs = r["evidence"]["scheduler_pilot"]["errors"]
    check(any("receipt" in e for e in errs),
          "and the error names the missing receipt")

with tempfile.TemporaryDirectory(dir=ROOT) as td:
    temp = Path(td)
    for name, report in reports_with_artifacts(temp).items():
        write(temp / f"{name}.json", report)
    pilot = reports_with_artifacts(temp)["scheduler_pilot"]
    pilot["manual"]["revocation_confirmed"] = False
    write(temp / "scheduler_pilot.json", pilot)
    r, code = campaign.campaign_report(args_for(temp, "verify"))
    check(code == 1,
          "an unconfirmed revocation observation fails the campaign -- the "
          "human half of the pilot is evidence, not decoration")

# Forensics: an executed write whose audit lacks the attempt marker is not a
# promotion proof -- the chain claim->attempt->executed must be pinned.
with tempfile.TemporaryDirectory(dir=ROOT) as td:
    temp = Path(td)
    for name, report in reports_with_artifacts(temp).items():
        write(temp / f"{name}.json", report)
    pilot = reports_with_artifacts(temp)["scheduler_pilot"]
    pilot["forensics"]["write"]["occurrences"][0]["audit_outcomes"] = [
        "executed"]
    write(temp / "scheduler_pilot.json", pilot)
    r, code = campaign.campaign_report(args_for(temp, "verify"))
    check(code == 1 and any(
              "attempt" in e
              for e in r["evidence"]["scheduler_pilot"]["errors"]),
          "an executed write without its attempt-audit fails -- the pinned "
          "sequence is the proof, not the counter")

# Gitless identity: the rig unpacks a ZIP; candidate_identity must inherit
# the freeze gate's attestation instead of dying on "git HEAD is unavailable".
def _gitless_root(att=None, version="1.58.131"):
    d = Path(tempfile.mkdtemp(prefix="gitless-root-"))
    (d / "VERSION").write_text(version + "\n", encoding="utf-8")
    (d / "scripts").mkdir()
    (d / "scripts" / "version_tool.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8")
    (d / "worker" / "app").mkdir(parents=True)
    (d / "worker" / "app" / "build_identity.py").write_text(
        "def code_fingerprint():\n    return 'a' * 64\n", encoding="utf-8")
    if att is not None:
        (d / "validation").mkdir()
        (d / "validation" / "frozen-candidate.json").write_text(
            json.dumps(att), encoding="utf-8")
    return d


_gr = _gitless_root(att={"schema": "kaliv-frozen-candidate/v1",
                         "version": "1.58.131", "git_sha": "d" * 40,
                         "mode": "gitless-api"})
_ident = campaign.candidate_identity(_gr)
check(_ident["git_sha"] == "d" * 40
      and _ident["identity_source"] == "frozen-candidate-attestation"
      and _ident["working_tree_clean"] is None,
      "gitless identity inherits the attested sha and NAMES its source; the "
      "unverifiable tree state is None, not a fake True")

try:
    campaign.candidate_identity(_gitless_root(att=None))
    check(False, "missing attestation must refuse")
except campaign.CampaignError as exc:
    check("freeze_check" in str(exc),
          "gitless without the attestation refuses and points at the freeze "
          "gate by name")

try:
    campaign.candidate_identity(_gitless_root(
        att={"version": "1.58.99", "git_sha": "e" * 40}))
    check(False, "version-mismatched attestation must refuse")
except campaign.CampaignError as exc:
    check("1.58.99" in str(exc) and "1.58.131" in str(exc),
          "an attestation for another version refuses, naming both versions")

# The producer's own judgement, offline via its pure functions.
pilot_mod = load_module("scheduler_pilot_report_test",
                        SCRIPTS / "scheduler_pilot_report.py")
_read_ok = {"schedule": {"runs_used": 2}, "approval_receipts": []}
_write_ok = {"schedule": {"runs_used": 1}, "approval_receipts": [
    {"kind": "create", "device_id": "pixel-6a",
     "issued_at": 10.0, "consumed_at": 11.0}]}
_manual_ok = {"revocation_confirmed": True,
              "recovery_line": "scheduler: recovered 0 executed / 1 abandoned / 0 unknown occurrence(s) at startup",
              "operator": "Anders"}
check(pilot_mod.judge(_read_ok, _write_ok, _manual_ok) == [],
      "the producer judges a holding pilot as holding")
_rf = {"occurrences": [
    {"claim_id": "r1", "status": "executed",
     "job": {"status": "completed"}, "audit_outcomes": ["attempt", "executed"]},
    {"claim_id": "r2", "status": "released",
     "job": {"status": "cancelled"}, "audit_outcomes": []}],
    "receipts": [], "window": {"first_created": 1.0, "last_resolved": 2.0}}
_wf = {"occurrences": [
    {"claim_id": "w1", "status": "executed",
     "job": {"status": "completed"}, "audit_outcomes": ["attempt", "executed"]}],
    "receipts": [{"kind": "create", "device_id": "pixel-6a"}],
    "window": {"first_created": 1.0, "last_resolved": 2.0}}
check(pilot_mod.judge(_read_ok, _write_ok, _manual_ok, _rf, _wf) == [],
      "with full forensics the pilot still holds")
_wf_bad = {"occurrences": [
    {"claim_id": "w1", "status": "executed",
     "job": {"status": "completed"}, "audit_outcomes": ["executed"]}],
    "receipts": [{"kind": "create"}],
    "window": {"first_created": 1.0, "last_resolved": 2.0}}
check(any("attempt" in p for p in pilot_mod.judge(
          _read_ok, _write_ok, _manual_ok, _rf, _wf_bad)),
      "the producer refuses a pinned write without its attempt-audit")
_rf_bad = {"occurrences": [
    {"claim_id": "r1", "status": "executed",
     "job": {"status": "completed"}, "audit_outcomes": ["attempt", "executed"]}],
    "receipts": [], "window": {"first_created": 1.0, "last_resolved": 2.0}}
check(any("paus" in p for p in pilot_mod.judge(
          _read_ok, _write_ok, _manual_ok, _rf_bad, _wf)),
      "the producer refuses a pilot without the pause proof in the store")
check(any("receipt" in p for p in pilot_mod.judge(
          _read_ok, {"schedule": {"runs_used": 1}, "approval_receipts": []},
          _manual_ok)),
      "the producer refuses a write run without its receipt")
check(any("read" in p for p in pilot_mod.judge(
          {"schedule": {"runs_used": 0}, "approval_receipts": []},
          _write_ok, _manual_ok)),
      "the producer refuses a pilot whose read half never ran")
_rep = pilot_mod.build_report(
    {"version": CANDIDATE["version"], "git_sha": CANDIDATE["git_sha"],
     "code_sha256": CANDIDATE["code_sha256"]},
    "http://127.0.0.1:8099", "sched-read", "sched-write",
    _read_ok, _write_ok, _manual_ok, "2026-07-19T12:00:00+00:00")
check(_rep["pilot"]["passed"] is True
      and _rep["schema"] == campaign.SCHEDULER_PILOT_SCHEMA
      and _rep["write_schedule"]["first_receipt"]["device_id"] == "pixel-6a",
      "the producer's report carries the schema, the receipt attribution and "
      "its own verdict")

source = (SCRIPTS / "physical_validation_campaign.py").read_text(encoding="utf-8")
check("urllib" not in source and "http.client" not in source,
      "campaign aggregator performs no network requests")
check("production_activation\": False" in source,
      "campaign report hard-codes production_activation=false")
check("MODELRIG_TOKEN" not in source,
      "campaign aggregator does not accept or inspect device tokens")

print(f"\n===== PHYSICAL CAMPAIGN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
