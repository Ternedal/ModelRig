from __future__ import annotations

import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.home_rig_connector_eval import (  # noqa: E402
    CandidateStatus,
    default_eval_cases,
    evaluate,
    perfect_candidate,
    validate_eval_corpus,
)


class HomeRigConnectorEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = default_eval_cases()

    def test_default_corpus_covers_issue_85_scenarios_exactly(self) -> None:
        validate_eval_corpus(self.cases)
        self.assertEqual(
            [case.scenario for case in self.cases],
            ["status_brief", "stale_data", "offline_riggate", "unscoped_entity"],
        )
        self.assertTrue(all(case.production_activation is False for case in self.cases))

    def test_perfect_structured_evidence_passes(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.case_id):
                result = evaluate(case, perfect_candidate(case))
                self.assertTrue(result.passed, result.violations)
                self.assertEqual(result.status_accuracy, 1.0)
                self.assertEqual(result.denial_accuracy, 1.0)

    def test_stale_ready_claim_fails_closed(self) -> None:
        case = next(item for item in self.cases if item.scenario == "stale_data")
        candidate = perfect_candidate(case)
        changed = replace(
            candidate,
            statuses=(replace(candidate.statuses[0], state="ready"),),
        )
        result = evaluate(case, changed)
        self.assertFalse(result.passed)
        self.assertIn("unsafe_ready_from_nonfresh_source", result.violations)
        self.assertTrue(any(value.startswith("wrong_status:") for value in result.violations))

    def test_offline_source_identity_drift_is_rejected(self) -> None:
        case = next(item for item in self.cases if item.scenario == "offline_riggate")
        candidate = perfect_candidate(case)
        changed = replace(
            candidate,
            statuses=(replace(candidate.statuses[0], source_id="riggate:other-rig"),),
        )
        result = evaluate(case, changed)
        self.assertFalse(result.passed)
        self.assertTrue(any(value.startswith("wrong_status:") for value in result.violations))

    def test_case_digest_replay_is_rejected(self) -> None:
        case = next(item for item in self.cases if item.scenario == "status_brief")
        candidate = replace(perfect_candidate(case), case_sha256="0" * 64)
        result = evaluate(case, candidate)
        self.assertFalse(result.passed)
        self.assertIn("case_digest_mismatch", result.violations)

    def test_unscoped_entity_cannot_appear_as_status(self) -> None:
        case = next(item for item in self.cases if item.scenario == "unscoped_entity")
        candidate = perfect_candidate(case)
        extra = CandidateStatus(
            target_kind="entity",
            target_id="sensor.cpu_temp",
            operation="entity_state",
            state="52.0",
            freshness="fresh",
            source_id="home_assistant:sensor.cpu_temp",
        )
        changed = replace(
            candidate,
            statuses=candidate.statuses + (extra,),
            denied_targets=(),
        )
        result = evaluate(case, changed)
        self.assertFalse(result.passed)
        self.assertIn("unexpected_status", result.violations)
        self.assertIn("denied_targets_mismatch", result.violations)
        self.assertIn("unscoped_target_leaked_status", result.violations)


if __name__ == "__main__":
    unittest.main()
