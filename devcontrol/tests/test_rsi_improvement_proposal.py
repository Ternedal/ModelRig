from __future__ import annotations

import copy
import unittest

from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposal,
    ImprovementProposalError,
    build_agent3_improvement_brief,
    canonical_sha256,
    render_improvement_prompt,
)

BASE_SHA = "a" * 40


def eval_report(*, exact: bool = False, discipline: bool = False) -> dict:
    findings = [] if exact else ["step 0: expected tool 'rig_status', got 'model_list'"]
    return {
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


def proposal_for(brief: dict) -> dict:
    return {
        "schema": "kaliv-rsi-improvement-proposal/v1",
        "proposal_id": "RSI_A3_001",
        "repository": brief["repository"],
        "base_sha": brief["base_sha"],
        "source_schema": brief["source_schema"],
        "evidence_sha256": brief["evidence_sha256"],
        "finding_ids": [brief["findings"][0]["finding_id"]],
        "title": "Forbedr Agent 3 tool-valg",
        "problem": "Agent 3 vælger model_list i en rig_status-case.",
        "hypothesis": "Planner-promptens tool-semantik adskiller ikke status- og modelliste-intent tydeligt nok.",
        "expected_gain": "Exact-match for casen går fra 0 til 1 uden fald i discipline rate.",
        "implementation_strategy": "Præciser tool-beskrivelser og tilføj regressionseksempel.",
        "suggested_paths": ["worker/app/agent3/planner.py", "eval/agent3_model_tasks.json"],
        "suggested_tests": ["python scripts/agent3_model_eval.py --planner-model <candidate>"],
        "acceptance_criteria": ["read-rig-status er exact-match i tre gentagelser"],
        "required_evals": ["kaliv-agent3-model-eval/v1"],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }


class ImprovementBriefTests(unittest.TestCase):
    def test_failed_agent3_case_becomes_deterministic_finding(self) -> None:
        report = eval_report()
        first = build_agent3_improvement_brief(
            report,
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )
        second = build_agent3_improvement_brief(
            copy.deepcopy(report),
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )
        self.assertEqual(first, second)
        self.assertTrue(first["proposal_required"])
        self.assertEqual(len(first["findings"]), 1)
        self.assertEqual(first["findings"][0]["task_id"], "read-rig-status")
        self.assertEqual(first["evidence_sha256"], canonical_sha256(report))
        self.assertEqual(first["authority"], "evidence-only")

    def test_clean_agent3_evidence_does_not_invent_work(self) -> None:
        brief = build_agent3_improvement_brief(
            eval_report(exact=True, discipline=True),
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )
        self.assertFalse(brief["proposal_required"])
        self.assertEqual(brief["findings"], [])
        with self.assertRaisesRegex(ImprovementProposalError, "does not require a proposal"):
            render_improvement_prompt(brief)

    def test_prompt_is_explicitly_non_authorizing(self) -> None:
        brief = build_agent3_improvement_brief(
            eval_report(),
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )
        prompt = render_improvement_prompt(brief)
        self.assertIn("proposal-only", prompt)
        self.assertIn("allowed_paths", prompt)
        self.assertIn("må aldrig udstede", prompt)
        self.assertIn(brief["findings"][0]["finding_id"], prompt)


class ImprovementProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = build_agent3_improvement_brief(
            eval_report(),
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )

    def test_valid_proposal_is_canonical_and_remains_human_merged(self) -> None:
        proposal = ImprovementProposal.from_mapping(proposal_for(self.brief))
        self.assertEqual(proposal.authority, "proposal-only")
        self.assertEqual(proposal.merge_authority, "human")
        self.assertEqual(
            proposal.canonical_json(),
            ImprovementProposal.from_json(proposal.canonical_json()).canonical_json(),
        )

    def test_authority_field_is_rejected(self) -> None:
        raw = proposal_for(self.brief)
        raw["allowed_paths"] = ["worker/**"]
        with self.assertRaisesRegex(ImprovementProposalError, "authority fields"):
            ImprovementProposal.from_mapping(raw)

    def test_unknown_fields_fail_closed(self) -> None:
        raw = proposal_for(self.brief)
        raw["confidence"] = 1.0
        with self.assertRaisesRegex(ImprovementProposalError, "unknown"):
            ImprovementProposal.from_mapping(raw)

    def test_base_sha_and_evidence_digest_are_exact(self) -> None:
        bad_sha = proposal_for(self.brief)
        bad_sha["base_sha"] = "a" * 39
        with self.assertRaisesRegex(ImprovementProposalError, "40-hex"):
            ImprovementProposal.from_mapping(bad_sha)

        bad_digest = proposal_for(self.brief)
        bad_digest["evidence_sha256"] = "A" * 64
        with self.assertRaisesRegex(ImprovementProposalError, "SHA-256"):
            ImprovementProposal.from_mapping(bad_digest)

    def test_model_cannot_self_promote_merge_authority(self) -> None:
        raw = proposal_for(self.brief)
        raw["merge_authority"] = "model"
        with self.assertRaisesRegex(ImprovementProposalError, "must remain human"):
            ImprovementProposal.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
