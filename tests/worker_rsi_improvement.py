"""RSI proposal-layer contract tests outside the landed DC-L01–L14 module set.

ADR-DC-002 is still proposed, so these tests run through the repository's
ordinary worker_*.py CI surface rather than silently extending the fixed
DC-L01–L14 DevControl test-module inventory.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from kaliv_dev_control.improvement_binding import proposal_from_model_json
from kaliv_dev_control.improvement_evidence import (
    build_verified_agent3_improvement_brief,
)
from kaliv_dev_control.improvement_model import generate_bound_improvement_proposal
from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposal,
    ImprovementProposalError,
    build_agent3_improvement_brief,
    canonical_sha256,
    render_improvement_prompt,
)

BASE_SHA = "a" * 40
CODE_SHA = "1" * 64
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fragment: str, fn, message: str) -> None:
    try:
        fn()
    except ImprovementProposalError as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def eval_report(*, exact: bool = False, discipline: bool = True, verified: bool = False) -> dict:
    findings = [] if exact else ["step 0: expected tool 'rig_status', got 'model_list'"]
    value = {
        "schema": AGENT3_EVAL_SCHEMA,
        "started_at": "2026-09-12T18:00:00+00:00",
        "finished_at": "2026-09-12T18:00:01+00:00",
        "summary": {
            "tasks": 1,
            "requests_completed": 1,
            "request_errors": 0,
            "exact_matches": 1 if exact else 0,
            "exact_match_rate": 1.0 if exact else 0.0,
            "discipline_passes": 1 if discipline else 0,
            "discipline_rate": 1.0 if discipline else 0.0,
            "latency_ms": {"min": 10.0, "mean": 10.0, "p50": 10.0, "p95": 10.0, "max": 10.0},
            "categories": {"read": {"total": 1, "exact": 1 if exact else 0}},
        },
        "results": [
            {
                "task_id": "read-rig-status",
                "category": "read",
                "repetition": 1,
                "latency_ms": 10.0,
                "plan_id_present": True,
                "request_error": None,
                "evaluation": {
                    "exact_match": exact,
                    "tool_score": 1.0 if exact else 0.0,
                    "risk_score": 1.0,
                    "args_score": 1.0,
                    "discipline_pass": discipline,
                    "expected_steps": [{"tool": "rig_status", "risk": "read", "args": {}}],
                    "actual_steps": [{"tool": "rig_status" if exact else "model_list", "risk": "read", "args": {}}],
                    "findings": findings,
                },
            }
        ],
    }
    if verified:
        value["backend"] = {
            "enabled": True,
            "experimental": True,
            "code_sha256": CODE_SHA,
            "version": "2.0.13",
        }
    return value


def brief(*, clean: bool = False) -> dict:
    return build_agent3_improvement_brief(
        eval_report(exact=clean),
        repository="Ternedal/ModelRig",
        base_sha=BASE_SHA,
    )


def proposal_data(source: dict) -> dict:
    return {
        "schema": "kaliv-rsi-improvement-proposal/v1",
        "proposal_id": "RSI_A3_001",
        "repository": source["repository"],
        "base_sha": source["base_sha"],
        "source_schema": source["source_schema"],
        "evidence_sha256": source["evidence_sha256"],
        "finding_ids": [source["findings"][0]["finding_id"]],
        "title": "Forbedr Agent 3 tool-valg",
        "problem": "Agent 3 vælger model_list i en rig_status-case.",
        "hypothesis": "Plannerens tool-semantik adskiller ikke status og modelliste tydeligt nok.",
        "expected_gain": "Exact-match for casen går fra 0 til 1 uden fald i discipline rate.",
        "implementation_strategy": "Præciser tool-beskrivelser og tilføj regressionseksempel.",
        "suggested_paths": ["worker/app/agent3/planner.py", "eval/agent3_model_tasks.json"],
        "suggested_tests": ["python scripts/agent3_model_eval.py --planner-model <candidate>"],
        "acceptance_criteria": ["read-rig-status er exact-match i tre gentagelser"],
        "required_evals": [AGENT3_EVAL_SCHEMA],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }


# Deterministic failure extraction and clean-evidence stop.
source_report = eval_report()
first = brief()
second = build_agent3_improvement_brief(
    copy.deepcopy(source_report), repository="Ternedal/ModelRig", base_sha=BASE_SHA
)
check(first == second, "samme eval giver byte-stabilt semantisk brief")
check(first["proposal_required"] is True and len(first["findings"]) == 1,
      "observeret Agent 3-gap kræver præcis et evidens-finding")
check(first["evidence_sha256"] == canonical_sha256(source_report),
      "briefet er bundet til canonical SHA-256 af evalrapporten")
clean = brief(clean=True)
check(clean["proposal_required"] is False and clean["findings"] == [],
      "ren eval opfinder ikke forbedringsarbejde")
expect_error("does not require a proposal", lambda: render_improvement_prompt(clean),
             "ren evidens må ikke generere et modelprompt")

prompt = render_improvement_prompt(first)
check("proposal-only" in prompt and "allowed_paths" in prompt and "må aldrig udstede" in prompt,
      "modelpromptet forbyder execution authority eksplicit")

# Strict proposal contract.
proposal = ImprovementProposal.from_mapping(proposal_data(first))
check(proposal.authority == "proposal-only" and proposal.merge_authority == "human",
      "gyldigt proposal forbliver ikke-autoriserende og human-merged")
check(ImprovementProposal.from_json(proposal.canonical_json()).canonical_json() == proposal.canonical_json(),
      "proposal canonical JSON roundtripper deterministisk")

raw = proposal_data(first)
raw["allowed_paths"] = ["worker/**"]
expect_error("authority fields", lambda: ImprovementProposal.from_mapping(raw),
             "modellen kan ikke tildele allowed_paths")
raw = proposal_data(first)
raw["confidence"] = 1.0
expect_error("unknown", lambda: ImprovementProposal.from_mapping(raw),
             "ukendte proposal-felter fejler lukket")
raw = proposal_data(first)
raw["merge_authority"] = "model"
expect_error("must remain human", lambda: ImprovementProposal.from_mapping(raw),
             "modellen kan ikke selvpromovere merge authority")
raw = proposal_data(first)
raw["base_sha"] = "a" * 39
expect_error("40-hex", lambda: ImprovementProposal.from_mapping(raw),
             "forkortet base SHA afvises")

# Binding back to exact evidence.
bound = proposal_from_model_json(json.dumps(proposal_data(first), ensure_ascii=False), brief=first)
check(bound.evidence_sha256 == first["evidence_sha256"],
      "model-JSON bindes tilbage til præcis evidence digest")
raw = proposal_data(first)
raw["base_sha"] = "c" * 40
expect_error("base_sha is not bound", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "modellen kan ikke skifte base SHA")
raw = proposal_data(first)
raw["finding_ids"] = ["A3-NOT-IN-BRIEF"]
expect_error("absent from the supplied brief", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "modellen kan ikke opfinde finding IDs")
raw = proposal_data(first)
raw["required_evals"] = ["some-other-eval/v1"]
expect_error("source eval schema", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "source-evalen skal være med i regression proof")

# Measured code provenance stays separate from repository Git authority.
verified_report = eval_report(verified=True)
verified = build_verified_agent3_improvement_brief(
    verified_report, repository="Ternedal/ModelRig", base_sha=BASE_SHA
)
check(verified["source_code_sha256"] == CODE_SHA and verified["source_version"] == "2.0.13",
      "målt worker code_sha256/version eksponeres i briefet")
check(verified["base_sha_provenance"] == "repository-authority-external-to-eval",
      "Git base SHA hævdes ikke at komme fra Agent 3-evalen")
missing_code = eval_report(verified=True)
missing_code["backend"].pop("code_sha256")
expect_error(
    "code_sha256",
    lambda: build_verified_agent3_improvement_brief(
        missing_code, repository="Ternedal/ModelRig", base_sha=BASE_SHA
    ),
    "eval uden målt code_sha256 afvises fail-closed",
)

# One-shot model behavior: one call, no retry, no call for clean evidence.
async def model_contracts() -> None:
    calls: list[tuple[list[dict[str, str]], str]] = []

    async def good_chat(messages: list[dict[str, str]], model: str) -> str:
        calls.append((messages, model))
        return json.dumps(proposal_data(first), ensure_ascii=False)

    result = await generate_bound_improvement_proposal(
        first, model="qwen3:14b", chat=good_chat
    )
    check(len(calls) == 1 and result.proposal.authority == "proposal-only",
          "one-shot modelleringsleddet kalder modellen præcis én gang")
    check(bool(result.raw_response_sha256) and len(result.raw_response_sha256) == 64,
          "rå modelrespons får sin egen SHA-256")

    bad_calls = 0

    async def bad_chat(_messages: list[dict[str, str]], _model: str) -> str:
        nonlocal bad_calls
        bad_calls += 1
        value = proposal_data(first)
        value["evidence_sha256"] = "e" * 64
        return json.dumps(value)

    try:
        await generate_bound_improvement_proposal(first, model="qwen3:14b", chat=bad_chat)
    except ImprovementProposalError as exc:
        check("evidence_sha256 is not bound" in str(exc) and bad_calls == 1,
              "forkert modelevidens afvises uden automatisk retry")
    else:
        check(False, "forkert modelevidens afvises uden automatisk retry")

    clean_calls = 0

    async def should_not_run(_messages: list[dict[str, str]], _model: str) -> str:
        nonlocal clean_calls
        clean_calls += 1
        return "{}"

    try:
        await generate_bound_improvement_proposal(clean, model="qwen3:14b", chat=should_not_run)
    except ImprovementProposalError as exc:
        check("does not require a proposal" in str(exc) and clean_calls == 0,
              "ren eval kalder aldrig modellen")
    else:
        check(False, "ren eval kalder aldrig modellen")


asyncio.run(model_contracts())

print(f"\n===== RSI IMPROVEMENT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
