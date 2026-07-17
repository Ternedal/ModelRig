from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.agent3.validation_gate import assess_report, evaluate_configured_report


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


CODE = "d" * 64  # what the rig said it was running


def make_report(now: float, *, decision: str = "deny", version: str = "1.58.38",
                code: str | None = CODE) -> dict:
    """code=None omits the field entirely -- an older rig that cannot say."""
    context_sha = "a" * 64
    memory_ids = ["memory/private-id"]
    read_receipt = {
        "requested": True,
        "sent_to_model": True,
        "target": "local",
        "included_ids": memory_ids,
        "excluded_ids": [],
        "character_count": 321,
        "sha256": context_sha,
    }
    if decision == "approve":
        write_state = "completed"
        mutation_expected = True
        write_events = [
            "run_created",
            "policy_decision",
            "confirmation_required",
            "confirmation_approved",
            "step_started",
            "step_succeeded",
            "run_completed",
        ]
    else:
        write_state = "cancelled"
        mutation_expected = False
        write_events = [
            "run_created",
            "policy_decision",
            "confirmation_required",
            "confirmation_denied",
        ]
    return {
        "schema": "kaliv-agent3-rig-validation/v1",
        "started_at": datetime.fromtimestamp(now - 120, timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
        "success": True,
        "host": {
            "hostname": "private-rig-hostname",
            "platform": "private-platform",
        },
        "target": {
            "base_url": "http://private-tailnet-address:8080",
            "planner_model": "qwen3:8b",
            "write_decision": decision,
            "modelrig_version": version,
            "worker_version": version,
            # A report now says which CODE the rig ran, not only what it called
            # itself (F-508). Two trees can carry the same semver.
            **({} if code is None else {"code_sha256": code}),
        },
        "validation": {
            "id": "private-validation-id",
            "memory_subject": "private-memory-subject",
            "marker_sha256": "c" * 64,
        },
        "checks": {
            "status": {
                "enabled": True,
                "experimental": True,
                "production_tools_path_untouched": True,
            },
            "memory_created": {
                "memory_id": memory_ids[0],
                "review_status": "confirmed",
            },
            "context_preview": {
                "included_ids": memory_ids,
                "excluded_ids": [],
                "character_count": 321,
                "sha256": context_sha,
                "sent_to_model": False,
            },
            "read_run": {
                "plan_id": "private-read-plan",
                "run_id": "private-read-run",
                "state": "completed",
                "receipt": deepcopy(read_receipt),
                "event_kinds": [
                    "run_created",
                    "policy_decision",
                    "step_started",
                    "step_succeeded",
                    "run_completed",
                ],
            },
            "write_preview": {
                "plan_id": "private-write-plan",
                "tool": "note_append",
                "risk": "write",
                "receipt": deepcopy(read_receipt),
            },
            "confirmation_card": {
                "run_id": "private-write-run",
                "step_id": "private-step-id",
                "summary": "private summary",
                "expires_at": now + 60,
                "digest_sha256": "b" * 64,
                "pre_confirmation_events": [
                    "run_created",
                    "policy_decision",
                    "confirmation_required",
                ],
            },
            "write_confirmation": {
                "decision": decision,
                "run_id": "private-write-run",
                "state": write_state,
                "event_kinds": write_events,
                "mutation_expected": mutation_expected,
            },
            "single_use": {"replay_blocked": True},
        },
        "cleanup": {
            "memory_id": memory_ids[0],
            "deleted": True,
            "lifecycle_status": "deleted",
            "content_erased": True,
            "source_ref_erased": True,
        },
        "error": None,
    }


now = 1_800_000_000.0

deny = assess_report(
    make_report(now, decision="deny"),
    current_version="1.58.38",
    current_code=CODE,
    now=now,
    report_sha256="d" * 64,
)
check(deny["eligible_for_developer_preview"] is True, "fresh deny report opens developer preview")
check(deny["eligible_for_write_pilot"] is False, "deny report cannot prove write execution")
check(deny["production_activation"] is False, "evidence never activates production")
check(deny["reasons"] == [], "valid deny report has no developer blockers")
check(deny["write_pilot_reasons"] == ["write_execution_not_proven"], "write pilot names its only missing proof")
check(deny["proofs"]["confirmation_path"] is True, "deny path proves immutable confirmation")
check(deny["proofs"]["write_execution"] is False, "deny path does not pretend to execute a write")

approved = assess_report(
    make_report(now, decision="approve"),
    current_version="1.58.38",
    current_code=CODE,
    now=now,
)
check(approved["eligible_for_developer_preview"] is True, "approved report retains developer eligibility")
check(approved["eligible_for_write_pilot"] is True, "approved report proves write pilot")
check(approved["proofs"]["write_execution"] is True, "approved event chain proves write execution")

stale_report = make_report(now)
stale_report["finished_at"] = datetime.fromtimestamp(now - 8 * 24 * 3600, timezone.utc).isoformat()
stale = assess_report(stale_report, current_version="1.58.38",
    current_code=CODE, now=now)
check(stale["fresh"] is False, "eight-day report is stale under seven-day default")
check("report_stale" in stale["reasons"], "stale report fails closed with explicit reason")

mismatch = assess_report(make_report(now), current_version="1.58.39",
    current_code=CODE, now=now)
check(mismatch["version_match"] is False, "old build evidence does not match current worker")
check("validated_version_mismatch" in mismatch["reasons"], "version mismatch blocks promotion")

receipt_tamper = make_report(now)
receipt_tamper["checks"]["write_preview"]["receipt"]["sha256"] = "e" * 64
receipt_result = assess_report(receipt_tamper, current_version="1.58.38",
    current_code=CODE, now=now)
check(receipt_result["proofs"]["memory_binding"] is False, "receipt SHA tampering is detected")
check("memory_binding_not_proven" in receipt_result["reasons"], "tampered memory binding blocks promotion")

pre_execution = make_report(now)
pre_execution["checks"]["confirmation_card"]["pre_confirmation_events"].append("step_started")
pre_result = assess_report(pre_execution, current_version="1.58.38",
    current_code=CODE, now=now)
check(pre_result["proofs"]["confirmation_path"] is False, "pre-confirmation execution is rejected")

outcome_mismatch = make_report(now, decision="deny")
outcome_mismatch["target"]["write_decision"] = "approve"
outcome_result = assess_report(outcome_mismatch, current_version="1.58.38",
    current_code=CODE, now=now)
check(outcome_result["eligible_for_developer_preview"] is False, "declared and actual write decisions must match")
check("write_decision_mismatch" in outcome_result["reasons"], "decision mismatch has explicit reason")

missing_model = make_report(now)
missing_model["target"]["planner_model"] = None
model_result = assess_report(missing_model, current_version="1.58.38",
    current_code=CODE, now=now)
check(model_result["eligible_for_developer_preview"] is False, "unidentified planner model cannot promote")
check("planner_model_missing" in model_result["reasons"], "missing planner model is explicit")

root = Path(tempfile.mkdtemp(prefix="agent3-validation-gate-"))
report_path = root / "report.json"
report = make_report(now)
report_path.write_text(json.dumps(report), encoding="utf-8")
from_file = evaluate_configured_report(
    current_version="1.58.38",
    current_code=CODE,
    environ={"KALIV_AGENT3_VALIDATION_REPORT": str(report_path)},
    now=now,
)
check(from_file["configured"] is True and from_file["present"] is True, "explicit report path is loaded")
check(from_file["eligible_for_developer_preview"] is True, "configured valid report evaluates successfully")
serialized = json.dumps(from_file, sort_keys=True)
for private_value in (
    "private-rig-hostname",
    "private-tailnet-address",
    "private-validation-id",
    "private-memory-subject",
    "private-read-run",
    "private-write-run",
    "memory/private-id",
):
    check(private_value not in serialized, f"assessment redacts {private_value}")

not_configured = evaluate_configured_report(
    current_version="1.58.38",
    current_code=CODE, environ={}, now=now
)
check(not_configured["configured"] is False, "no implicit report file is trusted")
check(not_configured["reasons"] == ["report_path_not_configured"], "missing config fails closed")

bad_json = root / "bad.json"
bad_json.write_text("{broken", encoding="utf-8")
bad_result = evaluate_configured_report(
    current_version="1.58.38",
    current_code=CODE,
    environ={"KALIV_AGENT3_VALIDATION_REPORT": str(bad_json)},
    now=now,
)
check(bad_result["reasons"] == ["report_invalid_json"], "malformed JSON is rejected")
check(isinstance(bad_result["report_sha256"], str), "malformed report still gets a forensic digest")

invalid_age = evaluate_configured_report(
    current_version="1.58.38",
    current_code=CODE,
    environ={
        "KALIV_AGENT3_VALIDATION_REPORT": str(report_path),
        "KALIV_AGENT3_VALIDATION_MAX_AGE_HOURS": "never",
    },
    now=now,
)
check(invalid_age["reasons"] == ["validation_max_age_invalid"], "invalid freshness config fails closed")

symlink_path = root / "report-link.json"
try:
    symlink_path.symlink_to(report_path)
except (OSError, NotImplementedError):
    print("  SKIP: symlink creation unavailable")
else:
    symlink_result = evaluate_configured_report(
        current_version="1.58.38",
    current_code=CODE,
        environ={"KALIV_AGENT3_VALIDATION_REPORT": str(symlink_path)},
        now=now,
    )
    check(symlink_result["reasons"] == ["report_symlink_not_allowed"], "symlink evidence is rejected")

# --- a report must say which CODE it tested, not which label (F-508) --------
# The gate compared validated_version to current_version and called it evidence.
# Two trees can carry the same semver -- every commit that does not bump makes
# another one -- so the check proved the rig agreed about a NUMBER. This report
# is the gate to everything else; a gate that checks a label is a gate.

no_code = assess_report(
    make_report(now, code=None),
    current_version="1.58.38",
    current_code=CODE,
    now=now,
)
check("validated_code_identity_missing" in no_code["reasons"],
      "a report that cannot say which code it tested is refused -- not weaker "
      "evidence, no evidence")
check(no_code["eligible_for_developer_preview"] is False,
      "and it opens nothing")

other_code = assess_report(
    make_report(now, code="e" * 64),
    current_version="1.58.38",
    current_code=CODE,
    now=now,
)
check("validated_code_mismatch" in other_code["reasons"],
      "a rig that ran DIFFERENT code from the tree being blessed is refused, "
      "even though the version string matches perfectly")
check(other_code["code_match"] is False, "and code_match says so plainly")

blind = assess_report(
    make_report(now),
    current_version="1.58.38",
    current_code=None,
    now=now,
)
check("current_code_identity_unavailable" in blind["reasons"],
      "a caller who cannot state the tree's identity gets a refusal, not a pass "
      "-- fail closed is the whole point of this file")

good = assess_report(make_report(now), current_version="1.58.38",
                     current_code=CODE, now=now)
check(good["code_match"] is True,
      "and a report from the same code on the same version matches")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
