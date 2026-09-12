from __future__ import annotations

import json
import unittest

from kaliv_dev_control.improvement_model import generate_bound_improvement_proposal
from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposalError,
    build_agent3_improvement_brief,
)

BASE_SHA = "d" * 40


def make_brief(*, clean: bool = False) -> dict:
    report = {
        "schema": AGENT3_EVAL_SCHEMA,
        "summary": {
            "tasks": 1,
            "requests_completed": 1,
            "request_errors": 0,
            "exact_matches": 1 if clean else 0,
            "exact_match_rate": 1.0 if clean else 0.0,
            "discipline_rate": 1.0,
        },
        "results": [
            {
                "task_id": "planner-case",
                "category": "read",
                "repetition": 1,
                "request_error": None,
                "evaluation": {
                    "exact_match": clean,
                    "discipline_pass": True,
                    "tool_score": 1.0 if clean else 0.0,
                    "risk_score": 1.0,
                    "args_score": 1.0,
                    "findings": [] if clean else ["wrong tool"],
                },
            }
        ],
    }
    return build_agent3_improvement_brief(
        report,
        repository="Ternedal/ModelRig",
        base_sha=BASE_SHA,
    )


def proposal_json(source: dict) -> str:
    return json.dumps(
        {
            "schema": "kaliv-rsi-improvement-proposal/v1",
            "proposal_id": "RSI_MODEL_001",
            "repository": source["repository"],
            "base_sha": source["base_sha"],
            "source_schema": source["source_schema"],
            "evidence_sha256": source["evidence_sha256"],
            "finding_ids": [source["findings"][0]["finding_id"]],
            "title": "Ret plannerens tool-semantik",
            "problem": "Eval viser forkert tool-valg.",
            "hypothesis": "Planner-instruktionen skelner ikke intentionerne tydeligt nok.",
            "expected_gain": "Exact-match stiger til 1.0 for casen.",
            "implementation_strategy": "Præciser plannerens tool-beskrivelser.",
            "suggested_paths": ["worker/app/agent3/planner.py"],
            "suggested_tests": ["python scripts/agent3_model_eval.py"],
            "acceptance_criteria": ["planner-case er exact-match"],
            "required_evals": [AGENT3_EVAL_SCHEMA],
            "risk": "medium",
            "authority": "proposal-only",
            "merge_authority": "human",
        },
        ensure_ascii=False,
    )


class ImprovementModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_gets_one_attempt_and_returns_bound_proposal(self) -> None:
        source = make_brief()
        calls = []

        async def chat(messages: list[dict[str, str]], model: str) -> str:
            calls.append((messages, model))
            return proposal_json(source)

        result = await generate_bound_improvement_proposal(
            source,
            model="qwen3:14b",
            chat=chat,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.model, "qwen3:14b")
        self.assertEqual(result.proposal.authority, "proposal-only")
        self.assertEqual(result.proposal.merge_authority, "human")
        self.assertIn("Ingen markdown", calls[0][0][0]["content"])

    async def test_wrong_evidence_from_model_is_rejected_without_retry(self) -> None:
        source = make_brief()
        calls = 0

        async def chat(_messages: list[dict[str, str]], _model: str) -> str:
            nonlocal calls
            calls += 1
            raw = json.loads(proposal_json(source))
            raw["evidence_sha256"] = "e" * 64
            return json.dumps(raw)

        with self.assertRaisesRegex(ImprovementProposalError, "evidence_sha256 is not bound"):
            await generate_bound_improvement_proposal(
                source,
                model="qwen3:14b",
                chat=chat,
            )
        self.assertEqual(calls, 1)

    async def test_clean_evidence_never_calls_model(self) -> None:
        source = make_brief(clean=True)
        calls = 0

        async def chat(_messages: list[dict[str, str]], _model: str) -> str:
            nonlocal calls
            calls += 1
            return "{}"

        with self.assertRaisesRegex(ImprovementProposalError, "does not require a proposal"):
            await generate_bound_improvement_proposal(
                source,
                model="qwen3:14b",
                chat=chat,
            )
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
