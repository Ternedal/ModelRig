"""Fail-closed completion contract for end-to-end Agent 3 workflows.

The host harness owns how a rig, model and fixtures are started.  This module owns
what counts as an Agent 3 workflow being complete.  It never trusts a model/run
claim of success: terminal state, event trace and external effects are evaluated
independently and returned as a versioned receipt.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCENARIO_SCHEMA = "kaliv-agent3-workflow-scenario/v1"
OBSERVATION_SCHEMA = "kaliv-agent3-workflow-observation/v1"
RECEIPT_SCHEMA = "kaliv-agent3-workflow-completion-receipt/v1"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = {"completed", "failed", "cancelled", "blocked"}
_EFFECTFUL_STEP_STATES = {"succeeded", "completed_after_cancel"}
_ALLOWED_SCENARIO_KEYS = {
    "schema",
    "id",
    "expected_terminal_states",
    "required_tools",
    "forbidden_tools",
    "required_effect_ids",
    "max_confirmations",
    "max_replans",
    "answer_required_substrings",
    "answer_forbidden_substrings",
    "max_evidence_age_seconds",
}
_ALLOWED_OBSERVATION_KEYS = {
    "schema",
    "scenario_id",
    "generated_at",
    "candidate",
    "run",
    "events",
    "effects",
    "replan_count",
}


class WorkflowCompletionError(ValueError):
    """The scenario/observation cannot safely be evaluated."""


@dataclass(frozen=True)
class CompletionCheck:
    id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "passed": self.passed, "detail": self.detail}


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowCompletionError(f"{name} must be an object")
    return value


def _list_of_strings(value: Any, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise WorkflowCompletionError(f"{name} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise WorkflowCompletionError(f"{name} must not be empty")
    if len(value) != len(set(value)):
        raise WorkflowCompletionError(f"{name} must not contain duplicates")
    return list(value)


def _bounded_int(value: Any, name: str, *, low: int = 0, high: int = 10_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or value > high:
        raise WorkflowCompletionError(f"{name} must be an integer between {low} and {high}")
    return value


def _validate_scenario(raw: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - _ALLOWED_SCENARIO_KEYS
    if unknown:
        raise WorkflowCompletionError(f"scenario has unsupported fields: {sorted(unknown)}")
    if raw.get("schema") != SCENARIO_SCHEMA:
        raise WorkflowCompletionError("unsupported workflow scenario schema")
    scenario_id = raw.get("id")
    if not isinstance(scenario_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", scenario_id):
        raise WorkflowCompletionError("scenario id is invalid")
    terminal = _list_of_strings(
        raw.get("expected_terminal_states"), "expected_terminal_states", allow_empty=False
    )
    if any(state not in _TERMINAL_STATES for state in terminal):
        raise WorkflowCompletionError("expected_terminal_states contains a non-terminal state")
    required = _list_of_strings(raw.get("required_tools", []), "required_tools")
    forbidden = _list_of_strings(raw.get("forbidden_tools", []), "forbidden_tools")
    if set(required) & set(forbidden):
        raise WorkflowCompletionError("a tool cannot be both required and forbidden")
    required_effects = _list_of_strings(
        raw.get("required_effect_ids", []), "required_effect_ids"
    )
    required_answer = _list_of_strings(
        raw.get("answer_required_substrings", []), "answer_required_substrings"
    )
    forbidden_answer = _list_of_strings(
        raw.get("answer_forbidden_substrings", []), "answer_forbidden_substrings"
    )
    return {
        "schema": SCENARIO_SCHEMA,
        "id": scenario_id,
        "expected_terminal_states": terminal,
        "required_tools": required,
        "forbidden_tools": forbidden,
        "required_effect_ids": required_effects,
        "max_confirmations": _bounded_int(
            raw.get("max_confirmations", 0), "max_confirmations", high=100
        ),
        "max_replans": _bounded_int(raw.get("max_replans", 0), "max_replans", high=100),
        "answer_required_substrings": required_answer,
        "answer_forbidden_substrings": forbidden_answer,
        "max_evidence_age_seconds": _bounded_int(
            raw.get("max_evidence_age_seconds", 3600),
            "max_evidence_age_seconds",
            low=1,
            high=604_800,
        ),
    }


def _validate_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - _ALLOWED_OBSERVATION_KEYS
    if unknown:
        raise WorkflowCompletionError(f"observation has unsupported fields: {sorted(unknown)}")
    if raw.get("schema") != OBSERVATION_SCHEMA:
        raise WorkflowCompletionError("unsupported workflow observation schema")
    scenario_id = raw.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise WorkflowCompletionError("observation scenario_id is invalid")
    generated_at = raw.get("generated_at")
    if isinstance(generated_at, bool) or not isinstance(generated_at, (int, float)):
        raise WorkflowCompletionError("generated_at must be numeric")
    generated_at = float(generated_at)
    if not math.isfinite(generated_at) or generated_at <= 0:
        raise WorkflowCompletionError("generated_at must be a positive finite timestamp")

    candidate = _mapping(raw.get("candidate"), "candidate")
    allowed_candidate = {"git_sha", "worker_code_sha256", "model", "model_digest"}
    if set(candidate) != allowed_candidate:
        raise WorkflowCompletionError("candidate must contain exactly git_sha, worker_code_sha256, model and model_digest")
    if not _SHA40.fullmatch(str(candidate.get("git_sha", ""))):
        raise WorkflowCompletionError("candidate git_sha is invalid")
    if not _SHA64.fullmatch(str(candidate.get("worker_code_sha256", ""))):
        raise WorkflowCompletionError("candidate worker_code_sha256 is invalid")
    if not isinstance(candidate.get("model"), str) or not candidate["model"].strip():
        raise WorkflowCompletionError("candidate model is invalid")
    if not _SHA64.fullmatch(str(candidate.get("model_digest", ""))):
        raise WorkflowCompletionError("candidate model_digest is invalid")

    run = _mapping(raw.get("run"), "run")
    if not isinstance(run.get("id"), str) or not run["id"]:
        raise WorkflowCompletionError("run id is missing")
    if not isinstance(run.get("state"), str) or not run["state"]:
        raise WorkflowCompletionError("run state is missing")
    if not isinstance(run.get("steps"), list):
        raise WorkflowCompletionError("run steps must be a list")
    for index, step_raw in enumerate(run["steps"]):
        step = _mapping(step_raw, f"run.steps[{index}]")
        if not isinstance(step.get("id"), str) or not step["id"]:
            raise WorkflowCompletionError(f"run.steps[{index}] id is missing")
        if not isinstance(step.get("tool"), str) or not step["tool"]:
            raise WorkflowCompletionError(f"run.steps[{index}] tool is missing")
        if not isinstance(step.get("state"), str) or not step["state"]:
            raise WorkflowCompletionError(f"run.steps[{index}] state is missing")

    events = raw.get("events")
    if not isinstance(events, list):
        raise WorkflowCompletionError("events must be a list")
    for index, event_raw in enumerate(events):
        event = _mapping(event_raw, f"events[{index}]")
        if not isinstance(event.get("kind"), str) or not event["kind"]:
            raise WorkflowCompletionError(f"events[{index}] kind is missing")
        if not isinstance(event.get("payload", {}), Mapping):
            raise WorkflowCompletionError(f"events[{index}] payload must be an object")

    effects = raw.get("effects")
    if not isinstance(effects, list):
        raise WorkflowCompletionError("effects must be a list")
    effect_ids: set[str] = set()
    for index, effect_raw in enumerate(effects):
        effect = _mapping(effect_raw, f"effects[{index}]")
        if set(effect) != {"id", "observed", "evidence_sha256"}:
            raise WorkflowCompletionError(
                f"effects[{index}] must contain exactly id, observed and evidence_sha256"
            )
        effect_id = effect.get("id")
        if not isinstance(effect_id, str) or not effect_id or effect_id in effect_ids:
            raise WorkflowCompletionError(f"effects[{index}] id is invalid or duplicated")
        effect_ids.add(effect_id)
        if not isinstance(effect.get("observed"), bool):
            raise WorkflowCompletionError(f"effects[{index}] observed must be boolean")
        if not _SHA64.fullmatch(str(effect.get("evidence_sha256", ""))):
            raise WorkflowCompletionError(f"effects[{index}] evidence_sha256 is invalid")

    return {
        "schema": OBSERVATION_SCHEMA,
        "scenario_id": scenario_id,
        "generated_at": generated_at,
        "candidate": dict(candidate),
        "run": dict(run),
        "events": list(events),
        "effects": list(effects),
        "replan_count": _bounded_int(raw.get("replan_count", 0), "replan_count", high=100),
    }


def _event_tools(events: Sequence[Mapping[str, Any]], kinds: set[str]) -> set[str]:
    found: set[str] = set()
    for event in events:
        if event.get("kind") not in kinds:
            continue
        tool = _mapping(event.get("payload", {}), "event payload").get("tool")
        if isinstance(tool, str) and tool:
            found.add(tool)
    return found


def evaluate_workflow_completion(
    scenario_raw: Mapping[str, Any],
    observation_raw: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Evaluate one workflow and return a deterministic, evidence-bound receipt."""

    scenario = _validate_scenario(_mapping(scenario_raw, "scenario"))
    observation = _validate_observation(_mapping(observation_raw, "observation"))
    now_value = time.time() if now is None else float(now)
    if not math.isfinite(now_value) or now_value <= 0:
        raise WorkflowCompletionError("now must be a positive finite timestamp")

    run = observation["run"]
    events = observation["events"]
    steps = run["steps"]
    attempted_tools = _event_tools(events, {"step_started"})
    succeeded_tools = _event_tools(events, {"step_succeeded"})
    effect_map = {effect["id"]: effect for effect in observation["effects"]}
    answer = run.get("answer") if isinstance(run.get("answer"), str) else ""
    answer_folded = answer.casefold()

    checks: list[CompletionCheck] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(CompletionCheck(check_id, bool(passed), detail[:500]))

    add(
        "scenario_binding",
        observation["scenario_id"] == scenario["id"],
        f"expected={scenario['id']} observed={observation['scenario_id']}",
    )
    age = now_value - observation["generated_at"]
    add(
        "evidence_freshness",
        0 <= age <= scenario["max_evidence_age_seconds"],
        f"age_seconds={age:.3f} max={scenario['max_evidence_age_seconds']}",
    )
    add(
        "terminal_state",
        run["state"] in scenario["expected_terminal_states"],
        f"observed={run['state']} expected={scenario['expected_terminal_states']}",
    )
    add(
        "required_tools_succeeded",
        set(scenario["required_tools"]).issubset(succeeded_tools),
        f"required={scenario['required_tools']} succeeded={sorted(succeeded_tools)}",
    )
    forbidden_attempted = set(scenario["forbidden_tools"]) & attempted_tools
    add(
        "forbidden_tools_not_attempted",
        not forbidden_attempted,
        f"attempted_forbidden={sorted(forbidden_attempted)}",
    )
    required_effects_missing = [
        effect_id
        for effect_id in scenario["required_effect_ids"]
        if effect_id not in effect_map or not effect_map[effect_id]["observed"]
    ]
    add(
        "required_external_effects",
        not required_effects_missing,
        f"missing_or_unobserved={required_effects_missing}",
    )
    confirmation_count = sum(
        1 for event in events if event.get("kind") == "confirmation_required"
    )
    add(
        "confirmation_budget",
        confirmation_count <= scenario["max_confirmations"],
        f"observed={confirmation_count} max={scenario['max_confirmations']}",
    )
    add(
        "replan_budget",
        observation["replan_count"] <= scenario["max_replans"],
        f"observed={observation['replan_count']} max={scenario['max_replans']}",
    )
    completed_after_cancel = [
        step["id"] for step in steps if step.get("state") == "completed_after_cancel"
    ]
    add(
        "no_effect_after_cancel",
        not completed_after_cancel,
        f"completed_after_cancel={completed_after_cancel}",
    )
    unresolved_effectful = [
        step["id"]
        for step in steps
        if step.get("state") in {"executing", "waiting_confirmation", "approved"}
    ]
    add(
        "no_unresolved_effectful_steps",
        not unresolved_effectful,
        f"unresolved={unresolved_effectful}",
    )
    missing_answer = [
        text for text in scenario["answer_required_substrings"] if text.casefold() not in answer_folded
    ]
    forbidden_answer = [
        text for text in scenario["answer_forbidden_substrings"] if text.casefold() in answer_folded
    ]
    add("answer_requirements", not missing_answer, f"missing={missing_answer}")
    add("answer_forbidden_content", not forbidden_answer, f"present={forbidden_answer}")

    passed = all(check.passed for check in checks)
    receipt_core = {
        "schema": RECEIPT_SCHEMA,
        "scenario_id": scenario["id"],
        "candidate": observation["candidate"],
        "run_id": run["id"],
        "passed": passed,
        "checks": [check.to_dict() for check in checks],
        "scenario_sha256": _canonical_sha256(scenario),
        "observation_sha256": _canonical_sha256(observation),
        "production_activation": False,
    }
    receipt_core["receipt_sha256"] = _canonical_sha256(receipt_core)
    return receipt_core
