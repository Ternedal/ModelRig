#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "scripts" / "agent3_termination_ui_physical_gate.py"
CAMPAIGN_PATH = ROOT / "scripts" / "physical_validation_termination_campaign.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("t023_physical_gate_test", GATE_PATH)
campaign = load("t023_physical_campaign_test", CAMPAIGN_PATH)

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
IDENTITY = {
    "version": "1.58.146",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "working_tree_clean": True,
    "dirty_entries": 0,
}
INVENTORY = {
    "none": ["tool:rig_status"],
    "cooperative": ["tool:pull_model"],
    "runtime": [],
}
CASES = ("non_interruptible", "cooperative_declaration", "late_completion")


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(raw)
    return raw


def case_values(root: Path, platform: str, name: str):
    cooperative = name == "cooperative_declaration"
    late = name == "late_completion"
    tool = "tool:pull_model" if cooperative else "tool:rig_status"
    semantics = "cooperative" if cooperative else "none"
    run_hash = sha(f"{platform}:{name}:run".encode("utf-8"))
    artifact_path = Path(
        f"validation/agent3-termination-ui-evidence/{platform}/{name}.json"
    )
    artifact_raw = write_json(
        root / artifact_path,
        {
            "candidate_git_sha": IDENTITY["git_sha"],
            "case": name,
            "platform": platform,
        },
    )
    observation = {
        "name": name,
        "surface": "developer_agent3" if cooperative else "normal_task",
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
        "run_id_sha256": run_hash,
        "receipt": {
            "plan": {
                "state_before": "available",
                "can_request_before": True,
                "effect_before": "prevent_future_steps_active_tool_continues",
                "state_after": "terminal",
                "can_request_after": False,
            },
            "model_stream": {
                "state": "not_active",
                "active": False,
                "handle_present": False,
                "can_request": False,
            },
            "active_tool": {
                "tool": tool,
                "semantics": semantics,
                "handle_present": False,
                "can_request": False,
                "request_state_before": "unavailable",
                "state_before": "executing",
                "request_state_after": "terminal",
                "state_after": "completed_after_cancel" if late else "cancelled",
                "cleanup_ms": None,
                "reason": "physically observed",
            },
        },
        "ui": {
            "shows_plan_scope": True,
            "shows_model_stream_scope": True,
            "shows_active_tool_scope": True,
            "shows_stop_plan": True,
            "shows_bare_stop": False,
            "shows_direct_tool_stop": False,
            "warns_active_tool_continues": True,
            "polls_after_plan_cancel": True,
            "shows_final_tool_state": True,
            "normal_chat_unchanged": True,
        },
        "artifact_path": str(artifact_path),
        "artifact_sha256": sha(artifact_raw),
    }
    report_case = {
        "name": name,
        "surface": observation["surface"],
        "run_id_sha256": run_hash,
        "tool": tool,
        "semantics": semantics,
        "handle_present": False,
        "state_after": observation["receipt"]["active_tool"]["state_after"],
        "request_state_after": "terminal",
        "artifact": {
            "path": str(artifact_path),
            "sha256": sha(artifact_raw),
            "bytes": len(artifact_raw),
        },
    }
    return observation, report_case


def make_termination_report(root: Path):
    inventory_hash = sha(canonical(INVENTORY))
    observations = {
        "schema": gate.OBSERVATIONS_SCHEMA,
        "prepared_at": NOW.isoformat().replace("+00:00", "Z"),
        "operator": "Anders",
        "candidate": {
            key: IDENTITY[key]
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "capability_inventory_sha256": inventory_hash,
        "platforms": {},
        "production_activation": False,
    }
    summary_platforms = {}
    for platform in gate.PLATFORMS:
        observed_cases = []
        report_cases = []
        for name in CASES:
            observed, report_case = case_values(root, platform, name)
            observed_cases.append(observed)
            report_cases.append(report_case)
        observations["platforms"][platform] = {
            "device_name": f"{platform}-device",
            "os_version": "test-os",
            "app_surface": "Kaliv Opgaver",
            "cases": observed_cases,
        }
        summary_platforms[platform] = {
            "device_name": f"{platform}-device",
            "os_version": "test-os",
            "cases": report_cases,
        }

    observations_path = Path("validation/agent3-termination-ui-observations.json")
    observations_raw = write_json(root / observations_path, observations)
    report = {
        "schema": gate.SCHEMA,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "success": True,
        "candidate": {
            key: IDENTITY[key]
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "capability_inventory": copy.deepcopy(INVENTORY),
        "capability_inventory_sha256": inventory_hash,
        "observations_path": str(observations_path),
        "observations_sha256": sha(observations_raw),
        "summary": {
            "required_cases": list(CASES),
            "runtime_capabilities": [],
            "runtime_handle_coverage": "not_applicable_no_runtime_capability",
            "window_started_at": NOW.isoformat().replace("+00:00", "Z"),
            "window_finished_at": NOW.isoformat().replace("+00:00", "Z"),
            "window_hours": 0.0,
            "age_hours": 0.0,
            "platforms": summary_platforms,
            "production_activation": False,
        },
        "errors": [],
        "production_activation": False,
    }
    report_path = Path("validation/agent3-termination-ui-physical-latest.json")
    write_json(root / report_path, report)
    return report, report_path, observations, observations_path


def candidate_base():
    proofs = list(campaign.CANDIDATE_BASE_PROOFS)
    return {
        "schema": campaign.CANDIDATE_SCHEMA,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "mode": "verify",
        "candidate": copy.deepcopy(IDENTITY),
        "proof_allowlist": proofs,
        "summary": {
            "total": len(proofs),
            "passed": proofs,
            "failed": [],
            "missing": [],
            "candidate_errors": [],
        },
        "gate": {
            "passed": True,
            "candidate_campaign_complete": True,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }


def final_base():
    proofs = [
        "preflight",
        "agent3",
        "model_eval",
        "voice",
        "rag",
        "lifecycle",
        "scheduler_pilot",
        "browser_peer_physical",
    ]
    return {
        "schema": campaign.FINAL_SCHEMA,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "candidate": copy.deepcopy(IDENTITY),
        "summary": {"total": 8, "passed": proofs, "errors": []},
        "gate": {
            "passed": True,
            "physical_campaign_complete": True,
            "browser_peer_physical_complete": True,
            "all_physical_evidence_complete": True,
            "production_activation": False,
        },
    }


checks = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


with tempfile.TemporaryDirectory(prefix="kaliv-t023-compose-") as tmp:
    root = Path(tmp)
    termination, termination_path, observations, observations_path = (
        make_termination_report(root)
    )

    errors, summary = gate.validate_report(
        root=root,
        report=termination,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check("independent T-023 validator accepts the complete baseline", errors == [])
    check(
        "baseline remains non-activating",
        summary.get("production_activation") is False
        and termination.get("production_activation") is False,
    )

    candidate_path = Path("validation/candidate-base.json")
    final_path = Path("validation/final-base.json")
    write_json(root / candidate_path, candidate_base())
    write_json(root / final_path, final_base())

    candidate_report, candidate_rc = campaign.evaluate(
        root=root,
        stage="candidate",
        base_path=candidate_path,
        termination_path=termination_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "candidate composition is exactly six plus T-023 equals seven",
        candidate_rc == 0
        and candidate_report["summary"]["total"] == 7
        and len(candidate_report["summary"]["passed"]) == 7
        and campaign.TERMINATION_NAME in candidate_report["summary"]["passed"],
    )
    check(
        "candidate composition remains release-pending and non-activating",
        candidate_report["gate"]["release_validation_pending"] is True
        and candidate_report["gate"]["production_activation"] is False,
    )

    final_report, final_rc = campaign.evaluate(
        root=root,
        stage="final",
        base_path=final_path,
        termination_path=termination_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "final composition is exactly eight plus T-023 equals nine",
        final_rc == 0
        and final_report["summary"]["total"] == 9
        and len(final_report["summary"]["passed"]) == 9
        and final_report["gate"]["all_physical_evidence_complete"] is True,
    )
    check(
        "final composition remains non-activating",
        final_report["gate"]["production_activation"] is False,
    )

    missing_report, missing_rc = campaign.evaluate(
        root=root,
        stage="candidate",
        base_path=candidate_path,
        termination_path=Path("validation/missing-t023.json"),
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "missing T-023 evidence is explicit and blocks composition",
        missing_rc == 1
        and missing_report["gate"]["passed"] is False
        and missing_report["evidence"]["termination_ui_physical"]["status"] == "missing",
    )

    changed = copy.deepcopy(termination)
    changed["candidate"]["git_sha"] = "c" * 40
    changed_path = Path("validation/changed-candidate-t023.json")
    write_json(root / changed_path, changed)
    changed_report, changed_rc = campaign.evaluate(
        root=root,
        stage="candidate",
        base_path=candidate_path,
        termination_path=changed_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "T-023 candidate drift blocks the composed receipt",
        changed_rc == 1
        and any("candidate.git_sha mismatch" in error for error in changed_report["summary"]["errors"]),
    )

    artifact_meta = termination["summary"]["platforms"]["android"]["cases"][0][
        "artifact"
    ]
    artifact = root / artifact_meta["path"]
    original_artifact = artifact.read_bytes()
    artifact.write_bytes(original_artifact + b"tamper")
    tampered_report, tampered_rc = campaign.evaluate(
        root=root,
        stage="final",
        base_path=final_path,
        termination_path=termination_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "artifact tamper blocks the final composition",
        tampered_rc == 1
        and any("does not match" in error for error in tampered_report["summary"]["errors"]),
    )
    artifact.write_bytes(original_artifact)

    stale_observations = copy.deepcopy(observations)
    stale = (NOW - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    stale_observations["prepared_at"] = stale
    for platform in gate.PLATFORMS:
        for case in stale_observations["platforms"][platform]["cases"]:
            case["observed_at"] = stale
    stale_raw = write_json(root / observations_path, stale_observations)
    stale_report = copy.deepcopy(termination)
    stale_report["observations_sha256"] = sha(stale_raw)
    stale_path = Path("validation/stale-t023.json")
    write_json(root / stale_path, stale_report)
    stale_composed, stale_rc = campaign.evaluate(
        root=root,
        stage="candidate",
        base_path=candidate_path,
        termination_path=stale_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "stale T-023 observations block the composed receipt",
        stale_rc == 1
        and any("old" in error for error in stale_composed["summary"]["errors"]),
    )
    write_json(root / observations_path, observations)

    duplicate_final = final_base()
    duplicate_final["summary"]["passed"][-1] = campaign.TERMINATION_NAME
    duplicate_path = Path("validation/duplicate-final-base.json")
    write_json(root / duplicate_path, duplicate_final)
    duplicate_report, duplicate_rc = campaign.evaluate(
        root=root,
        stage="final",
        base_path=duplicate_path,
        termination_path=termination_path,
        candidate=IDENTITY,
        now=NOW,
        max_age_hours=168.0,
    )
    check(
        "proof-name collision blocks the final composition",
        duplicate_rc == 1
        and any("already contains" in error for error in duplicate_report["summary"]["errors"]),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-023 PHYSICAL CAMPAIGN COMPOSITION: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
