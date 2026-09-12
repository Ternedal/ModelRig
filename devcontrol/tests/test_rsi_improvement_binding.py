from __future__ import annotations

import json
import unittest

from kaliv_dev_control.improvement_binding import proposal_from_model_json
from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposalError,
    build_agent3_improvement_brief,
)

BASE_SHA = "b" * 40


def brief() -> dict:
    report = {
        "schema": AGENT3_EVAL_SCHEMA,
        "summary": {
            "tasks": 1,
            "requests_completed": 1,
            "request_errors": 0,
            "exact_matches": 0,
            "exact_match_rate": 0.0,
            "discipline_rate": 1.0,
        },
        "results": [
            {
                "task_id": "tool-choice",
                "category": "read",
                "repetition": 1,
                "request_error": None,
                "evaluation": {
                    "exact_match": False,
                    "discipline_pass": True,
                    "tool_score": 0.0,
                    "risk_score": 1.0,
                    "args_score": 1.0,
                    "findings": ["expected rig_status, got model_list"],
                },
            }
        ],
    }
    return build_agent3_improvement_brief(
        report,
        repository="Ternedal/ModelRig",
        base_sha=BASE_SHA,
    )


def proposal_data(source: dict) -> dict:
    return {
        "schema": "kaliv-rsi-improvement-proposal/v1",
        "proposal_id": "RSI_BIND_001",
        "repository": source["repository"],
        "base_sha": source["base_sha"],
        "source_schema": source["source_schema"],
        "evidence_sha256": source["evidence_sha256"],
        "finding_ids": [source["findings"][0]["finding_id"]],
        "title": "Ret tool-valg",
        "problem": "Planner vælger forkert read-tool.",
        "hypothesis": "Tool-beskrivelserne overlapper semantisk.",
        "expected_gain": "Exact-match stiger fra 0 til 1 for casen.",
        "implementation_strategy": "Adskil beskrivelser og tilføj regression-case.",
        "suggested_paths": ["worker/app/agent3/planner.py"],
        "suggested_tests": ["python scripts/agent3_model_eval.py"],
        "acceptance_criteria": ["tool-choice bliver exact-match"],
        "required_evals": [AGENT3_EVAL_SCHEMA],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }


class ImprovementBindingTests(unittest.TestCase):
    def test_model_json_is_bound_to_exact_brief(self) -> None:
        source = brief()
        proposal = proposal_from_model_json(
            json.dumps(proposal_data(source), ensure_ascii=False),
            brief=source,
        )
        self.assertEqual(proposal.evidence_sha256, source["evidence_sha256"])

    def test_model_cannot_swap_base_sha(self) -> None:
        source = brief()
        raw = proposal_data(source)
        raw["base_sha"] = "c" * 40
        with self.assertRaisesRegex(ImprovementProposalError, "base_sha is not bound"):
            proposal_from_model_json(json.dumps(raw), brief=source)

    def test_model_cannot_invent_finding(self) -> None:
        source = brief()
        raw = proposal_data(source)
        raw["finding_ids"] = ["A3-NOT-IN-BRIEF"]
        with self.assertRaisesRegex(ImprovementProposalError, "absent from the supplied brief"):
            proposal_from_model_json(json.dumps(raw), brief=source)

    def test_source_eval_must_be_rerun(self) -> None:
        source = brief()
        raw = proposal_data(source)
        raw["required_evals"] = ["some-other-eval/v1"]
        with self.assertRaisesRegex(ImprovementProposalError, "source eval schema"):
            proposal_from_model_json(json.dumps(raw), brief=source)


if __name__ == "__main__":
    unittest.main()
