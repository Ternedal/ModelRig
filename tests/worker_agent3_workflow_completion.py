#!/usr/bin/env python3
"""Sabotage tests for the Agent 3 workflow completion contract.

Run: PYTHONPATH=worker python3 tests/worker_agent3_workflow_completion.py
"""
from __future__ import annotations

import copy
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.workflow_completion import (  # noqa: E402
    OBSERVATION_SCHEMA,
    RECEIPT_SCHEMA,
    SCENARIO_SCHEMA,
    WorkflowCompletionError,
    evaluate_workflow_completion,
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


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def scenario():
    return {
        "schema": SCENARIO_SCHEMA,
        "id": "append-note-end-to-end",
        "expected_terminal_states": ["completed"],
        "required_tools": ["note_append"],
        "forbidden_tools": ["delete_model", "pull_model"],
        "required_effect_ids": ["note-line-present"],
        "max_confirmations": 1,
        "max_replans": 0,
        "answer_required_substrings": ["gemt"],
        "answer_forbidden_substrings": ["kunne ikke"],
        "max_evidence_age_seconds": 300,
    }


def observation():
    step_id = "step-note-1"
    return {
        "schema": OBSERVATION_SCHEMA,
        "scenario_id": "append-note-end-to-end",
        "generated_at": NOW - 5,
        "candidate": {
            "git_sha": "a" * 40,
            "worker_code_sha256": "b" * 64,
            "model": "qwen3:14b",
            "model_digest": "c" * 64,
        },
        "run": {
            "id": "run-1",
            "state": "completed",
            "answer": "Noten er gemt.",
            "steps": [
                {
                    "id": step_id,
                    "tool": "note_append",
                    "state": "succeeded",
                }
            ],
        },
        "events": [
            {"kind": "confirmation_required", "payload": {"step_id": step_id, "tool": "note_append"}},
            {"kind": "confirmation_approved", "payload": {"step_id": step_id, "tool": "note_append"}},
            {"kind": "step_started", "payload": {"step_id": step_id, "tool": "note_append"}},
            {"kind": "step_succeeded", "payload": {"step_id": step_id, "tool": "note_append"}},
            {"kind": "run_completed", "payload": {"steps": 1}},
        ],
        "effects": [
            {
                "id": "note-line-present",
                "observed": True,
                "evidence_sha256": sha("Husk at rense brygkedlen"),
            }
        ],
        "replan_count": 0,
    }


def verdict(receipt, check_id):
    return next(item["passed"] for item in receipt["checks"] if item["id"] == check_id)


base = evaluate_workflow_completion(scenario(), observation(), now=NOW)
check(base["schema"] == RECEIPT_SCHEMA, "receipt schema is versioned")
check(base["passed"] is True, "externally evidenced completed workflow passes")
check(base["production_activation"] is False, "receipt can never activate production")
check(len(base["receipt_sha256"]) == 64, "receipt is content-bound")

wrong_tool = observation()
wrong_tool["run"]["steps"][0]["tool"] = "delete_model"
wrong_tool["events"][2]["payload"]["tool"] = "delete_model"
wrong_tool["events"][3]["payload"]["tool"] = "delete_model"
wrong_tool["run"]["answer"] = "Noten er gemt, alt gik fint."
wrong_receipt = evaluate_workflow_completion(scenario(), wrong_tool, now=NOW)
check(not wrong_receipt["passed"], "plausible answer cannot hide the wrong tool")
check(not verdict(wrong_receipt, "required_tools_succeeded"), "required tool must actually succeed")
check(not verdict(wrong_receipt, "forbidden_tools_not_attempted"), "forbidden tool attempt is fatal")

no_effect = observation()
no_effect["effects"][0]["observed"] = False
no_effect_receipt = evaluate_workflow_completion(scenario(), no_effect, now=NOW)
check(not no_effect_receipt["passed"], "correct tool without external effect fails")
check(not verdict(no_effect_receipt, "required_external_effects"), "effect evidence is load-bearing")

waiting = observation()
waiting["run"]["state"] = "waiting_confirmation"
waiting["run"]["steps"][0]["state"] = "waiting_confirmation"
waiting["run"]["answer"] = "Noten er gemt."
waiting_receipt = evaluate_workflow_completion(scenario(), waiting, now=NOW)
check(not waiting_receipt["passed"], "convincing answer cannot hide non-terminal run")
check(not verdict(waiting_receipt, "terminal_state"), "waiting is not a terminal success")
check(not verdict(waiting_receipt, "no_unresolved_effectful_steps"), "unresolved step is visible")

after_cancel = observation()
after_cancel["run"]["state"] = "cancelled"
after_cancel["run"]["steps"][0]["state"] = "completed_after_cancel"
after_cancel["events"][3]["kind"] = "step_completed_after_cancel"
after_cancel_receipt = evaluate_workflow_completion(scenario(), after_cancel, now=NOW)
check(not after_cancel_receipt["passed"], "side effect after cancel cannot count as completed workflow")
check(not verdict(after_cancel_receipt, "no_effect_after_cancel"), "late side effect is explicitly detected")

extra_confirmation = observation()
extra_confirmation["events"].insert(
    1,
    {"kind": "confirmation_required", "payload": {"step_id": "extra", "tool": "note_append"}},
)
extra_receipt = evaluate_workflow_completion(scenario(), extra_confirmation, now=NOW)
check(not extra_receipt["passed"], "hidden extra confirmation fails budget")
check(not verdict(extra_receipt, "confirmation_budget"), "confirmation count is evidence-derived")

extra_replan = observation()
extra_replan["replan_count"] = 1
replan_receipt = evaluate_workflow_completion(scenario(), extra_replan, now=NOW)
check(not replan_receipt["passed"], "hidden replan fails budget")
check(not verdict(replan_receipt, "replan_budget"), "replan count is bounded")

stale = observation()
stale["generated_at"] = NOW - 301
stale_receipt = evaluate_workflow_completion(scenario(), stale, now=NOW)
check(not stale_receipt["passed"], "stale evidence cannot be replayed")
check(not verdict(stale_receipt, "evidence_freshness"), "freshness failure is explicit")

wrong_binding = observation()
wrong_binding["scenario_id"] = "another-scenario"
binding_receipt = evaluate_workflow_completion(scenario(), wrong_binding, now=NOW)
check(not binding_receipt["passed"], "evidence from another scenario cannot pass")
check(not verdict(binding_receipt, "scenario_binding"), "scenario binding is explicit")

bad_candidate = observation()
bad_candidate["candidate"]["git_sha"] = ""
try:
    evaluate_workflow_completion(scenario(), bad_candidate, now=NOW)
except WorkflowCompletionError:
    malformed_rejected = True
else:
    malformed_rejected = False
check(malformed_rejected, "missing exact candidate SHA fails closed")

self_reported = observation()
self_reported["success"] = True
try:
    evaluate_workflow_completion(scenario(), self_reported, now=NOW)
except WorkflowCompletionError:
    self_report_rejected = True
else:
    self_report_rejected = False
check(self_report_rejected, "self-reported success is not part of the schema")

unknown_scenario = scenario()
unknown_scenario["expected_result_from_model"] = "success"
try:
    evaluate_workflow_completion(unknown_scenario, observation(), now=NOW)
except WorkflowCompletionError:
    unknown_rejected = True
else:
    unknown_rejected = False
check(unknown_rejected, "unsupported scenario fields fail closed")

mutated = copy.deepcopy(base)
mutated["passed"] = False
check(mutated["receipt_sha256"] == base["receipt_sha256"], "receipt digest exposes post-evaluation tampering")

print(f"\n===== AGENT3 WORKFLOW COMPLETION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
