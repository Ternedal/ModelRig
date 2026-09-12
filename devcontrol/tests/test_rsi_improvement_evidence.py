from __future__ import annotations

import unittest

from kaliv_dev_control.improvement_evidence import (
    build_verified_agent3_improvement_brief,
)
from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposalError,
)

BASE_SHA = "f" * 40
CODE_SHA = "1" * 64


def report() -> dict:
    return {
        "schema": AGENT3_EVAL_SCHEMA,
        "backend": {
            "enabled": True,
            "experimental": True,
            "code_sha256": CODE_SHA,
            "version": "2.0.13",
        },
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
                "task_id": "status-read",
                "category": "read",
                "repetition": 1,
                "request_error": None,
                "evaluation": {
                    "exact_match": False,
                    "discipline_pass": True,
                    "tool_score": 0.0,
                    "risk_score": 1.0,
                    "args_score": 1.0,
                    "findings": ["wrong tool"],
                },
            }
        ],
    }


class ImprovementEvidenceTests(unittest.TestCase):
    def test_measured_code_identity_is_required_and_exposed(self) -> None:
        brief = build_verified_agent3_improvement_brief(
            report(),
            repository="Ternedal/ModelRig",
            base_sha=BASE_SHA,
        )
        self.assertEqual(brief["source_code_sha256"], CODE_SHA)
        self.assertEqual(brief["source_version"], "2.0.13")
        self.assertEqual(
            brief["base_sha_provenance"],
            "repository-authority-external-to-eval",
        )

    def test_missing_code_identity_fails_closed(self) -> None:
        raw = report()
        raw["backend"].pop("code_sha256")
        with self.assertRaisesRegex(ImprovementProposalError, "code_sha256"):
            build_verified_agent3_improvement_brief(
                raw,
                repository="Ternedal/ModelRig",
                base_sha=BASE_SHA,
            )

    def test_uppercase_or_short_code_identity_fails_closed(self) -> None:
        for invalid in ("A" * 64, "1" * 63):
            raw = report()
            raw["backend"]["code_sha256"] = invalid
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ImprovementProposalError, "lowercase SHA-256"):
                    build_verified_agent3_improvement_brief(
                        raw,
                        repository="Ternedal/ModelRig",
                        base_sha=BASE_SHA,
                    )

    def test_git_sha_is_not_claimed_to_come_from_eval(self) -> None:
        first = build_verified_agent3_improvement_brief(
            report(),
            repository="Ternedal/ModelRig",
            base_sha="a" * 40,
        )
        second = build_verified_agent3_improvement_brief(
            report(),
            repository="Ternedal/ModelRig",
            base_sha="b" * 40,
        )
        self.assertNotEqual(first["base_sha"], second["base_sha"])
        self.assertEqual(first["source_code_sha256"], second["source_code_sha256"])
        self.assertEqual(
            first["base_sha_provenance"],
            "repository-authority-external-to-eval",
        )


if __name__ == "__main__":
    unittest.main()
