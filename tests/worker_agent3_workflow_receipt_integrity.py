#!/usr/bin/env python3
"""Integrity tests for Agent 3 workflow completion receipts."""
from __future__ import annotations

import copy
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.workflow_completion import (  # noqa: E402
    OBSERVATION_SCHEMA,
    SCENARIO_SCHEMA,
    WorkflowCompletionError,
    evaluate_workflow_completion,
)
from app.agent3.workflow_completion_receipt import (  # noqa: E402
    verify_workflow_completion_receipt,
)

passed = failed = 0
NOW = 2_000_000_000.0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejects(receipt):
    try:
        verify_workflow_completion_receipt(receipt)
    except WorkflowCompletionError:
        return True
    return False


scenario = {
    "schema": SCENARIO_SCHEMA,
    "id": "receipt-integrity",
    "expected_terminal_states": ["completed"],
    "required_tools": ["rig_status"],
    "forbidden_tools": [],
    "required_effect_ids": [],
    "max_confirmations": 0,
    "max_replans": 0,
    "answer_required_substrings": ["klar"],
    "answer_forbidden_substrings": [],
    "max_evidence_age_seconds": 60,
}
observation = {
    "schema": OBSERVATION_SCHEMA,
    "scenario_id": "receipt-integrity",
    "generated_at": NOW - 1,
    "candidate": {
        "git_sha": "1" * 40,
        "worker_code_sha256": "2" * 64,
        "model": "qwen3:14b",
        "model_digest": "3" * 64,
    },
    "run": {
        "id": "run-integrity",
        "state": "completed",
        "answer": "Riggen er klar.",
        "steps": [{"id": "step-1", "tool": "rig_status", "state": "succeeded"}],
    },
    "events": [
        {"kind": "step_started", "payload": {"step_id": "step-1", "tool": "rig_status"}},
        {"kind": "step_succeeded", "payload": {"step_id": "step-1", "tool": "rig_status"}},
        {"kind": "run_completed", "payload": {"steps": 1}},
    ],
    "effects": [],
    "replan_count": 0,
}

receipt = evaluate_workflow_completion(scenario, observation, now=NOW)
verified = verify_workflow_completion_receipt(receipt)
check(verified == receipt, "untampered receipt verifies")

changed_verdict = copy.deepcopy(receipt)
changed_verdict["passed"] = False
check(rejects(changed_verdict), "changed top-level verdict is rejected")

changed_check = copy.deepcopy(receipt)
changed_check["checks"][0]["passed"] = False
check(rejects(changed_check), "changed check verdict is rejected")

changed_candidate = copy.deepcopy(receipt)
changed_candidate["candidate"]["model"] = "another-model"
check(rejects(changed_candidate), "changed candidate binding is rejected")

activation = copy.deepcopy(receipt)
activation["production_activation"] = True
check(rejects(activation), "receipt cannot be mutated into activation")

extra_field = copy.deepcopy(receipt)
extra_field["self_reported_success"] = True
check(rejects(extra_field), "unknown self-report field is rejected")

rehashed_lie = copy.deepcopy(receipt)
rehashed_lie["checks"][0]["passed"] = False
core = {key: value for key, value in rehashed_lie.items() if key != "receipt_sha256"}
raw = __import__("json").dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
rehashed_lie["receipt_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
check(rejects(rehashed_lie), "rehashed inconsistent verdict is rejected")

print(f"\n===== AGENT3 WORKFLOW RECEIPT INTEGRITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
