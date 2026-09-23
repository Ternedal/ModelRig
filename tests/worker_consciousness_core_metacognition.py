#!/usr/bin/env python3
"""C5 prediction/metacognition tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_metacognition.py
"""
from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveProfile,
    MetacognitionContractError,
    MetacognitiveState,
    OutcomeObservation,
    PredictionRecord,
    PredictionResolution,
    ThoughtProposal,
    ThoughtRequest,
    apply_resolution,
    initial_metacognitive_state,
    prediction_from_proposal,
    resolve_prediction,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


class ConsciousnessCoreMetacognitionTests(unittest.TestCase):
    def request(self) -> ThoughtRequest:
        return ThoughtRequest.model_validate(copy.deepcopy(FIXTURES["thought_request"]))

    def proposal(self) -> ThoughtProposal:
        return ThoughtProposal.model_validate(copy.deepcopy(FIXTURES["thought_proposal"]))

    def profile(self) -> CognitiveProfile:
        return CognitiveProfile.model_validate(copy.deepcopy(FIXTURES["cognitive_profile"]))

    def prediction(self, expected: str = "tool_result") -> PredictionRecord:
        return prediction_from_proposal(
            self.request(),
            self.proposal(),
            outcome_index=0,
            subject_ref="system:modelrig",
            expected_observation_kind=expected,
            source_refs=["cycle:evidence:1"],
        )

    def outcome(
        self,
        prediction: PredictionRecord,
        *,
        kind: str = "tool_result",
        relation: str = "supports",
    ) -> OutcomeObservation:
        return OutcomeObservation(
            schema="kaliv-consciousness-core/outcome-observation/v1",
            outcome_id="out-" + "4" * 32,
            prediction_id=prediction.prediction_id,
            observed_proposition="Observed bounded outcome.",
            observation_kind=kind,
            prediction_relation=relation,
            source_refs=["tool-receipt:1"],
            confidence=1.0,
            observed_sequence=7,
            production_activation=False,
        )

    def test_prediction_from_model_proposal_is_always_open(self) -> None:
        prediction = self.prediction()
        self.assertEqual(prediction.status, "open")
        self.assertEqual(
            prediction.created_from_thought_proposal_ref,
            "thought-proposal:" + self.proposal().proposal_id,
        )
        self.assertIn(
            "thought-proposal:" + self.proposal().proposal_id,
            prediction.source_refs,
        )
        self.assertFalse(prediction.production_activation)

    def test_proposal_cannot_choose_resolved_prediction_status(self) -> None:
        fields = set(ThoughtProposal.model_fields)
        self.assertNotIn("prediction_status", fields)
        self.assertNotIn("resolved_prediction", fields)
        prediction = self.prediction()
        self.assertEqual(prediction.status, "open")

    def test_bad_confidence_values_fail_closed(self) -> None:
        base = self.prediction().model_dump(mode="json")
        for value in (True, -0.01, 1.01, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                payload = copy.deepcopy(base)
                payload["confidence_before"] = value
                with self.assertRaises(ValidationError):
                    PredictionRecord.model_validate(payload)

    def test_outcome_requires_provenance(self) -> None:
        prediction = self.prediction()
        payload = self.outcome(prediction).model_dump(mode="json")
        payload["source_refs"] = []
        with self.assertRaises(ValidationError):
            OutcomeObservation.model_validate(payload)

    def test_user_report_and_tool_observation_remain_distinct(self) -> None:
        prediction = self.prediction(expected="any")
        user = self.outcome(prediction, kind="user_report")
        tool = self.outcome(prediction, kind="tool_result")
        self.assertEqual(user.observation_kind, "user_report")
        self.assertEqual(tool.observation_kind, "tool_result")
        self.assertNotEqual(user.observation_kind, tool.observation_kind)

    def test_resolution_is_deterministic_from_structured_relation(self) -> None:
        prediction = self.prediction()
        cases = {
            "supports": ("match", 0.0, 0.05),
            "partially_supports": ("partial", 0.5, -0.05),
            "contradicts": ("mismatch", 1.0, -0.20),
            "unknown": ("indeterminate", 0.5, 0.0),
        }
        for relation, expected in cases.items():
            with self.subTest(relation=relation):
                resolved = resolve_prediction(
                    prediction,
                    self.outcome(prediction, relation=relation),
                )
                self.assertEqual(
                    (resolved.result, resolved.error_score, resolved.confidence_delta_candidate),
                    expected,
                )
                self.assertTrue(resolved.evidence_refs)
                self.assertFalse(resolved.production_activation)

    def test_wrong_observation_kind_is_indeterminate(self) -> None:
        prediction = self.prediction(expected="embodiment")
        observed = self.outcome(prediction, kind="tool_result", relation="supports")
        resolved = resolve_prediction(prediction, observed)
        self.assertEqual(resolved.result, "indeterminate")
        self.assertEqual(resolved.error_score, 0.5)
        self.assertEqual(resolved.confidence_delta_candidate, 0.0)

    def test_only_open_prediction_can_be_resolved(self) -> None:
        prediction = self.prediction()
        closed = prediction.model_copy(update={"status": "resolved"})
        with self.assertRaises(MetacognitionContractError):
            resolve_prediction(closed, self.outcome(prediction))

    def test_outcome_must_bind_to_exact_prediction(self) -> None:
        prediction = self.prediction()
        other = self.outcome(prediction).model_copy(
            update={"prediction_id": "pred-" + "9" * 32}
        )
        with self.assertRaises(MetacognitionContractError):
            resolve_prediction(prediction, other)

    def test_mismatch_changes_strategy_not_execution_authority(self) -> None:
        prediction = self.prediction()
        resolution = resolve_prediction(
            prediction,
            self.outcome(prediction, relation="contradicts"),
        )
        state = initial_metacognitive_state(self_ref="self-state:1")
        updated = apply_resolution(state, resolution, self.profile())
        self.assertTrue(updated.verification_required)
        self.assertTrue(updated.decomposition_required)
        self.assertGreaterEqual(updated.current_task_uncertainty, 0.75)
        self.assertNotIn("actions", MetacognitiveState.model_fields)
        self.assertNotIn("tools", MetacognitiveState.model_fields)
        self.assertNotIn("agent3", MetacognitiveState.model_fields)

    def test_cognitive_profile_changes_capacity_not_identity_state(self) -> None:
        prediction = self.prediction()
        resolution = resolve_prediction(
            prediction,
            self.outcome(prediction, relation="supports"),
        )
        state = initial_metacognitive_state(self_ref="self-state:1")
        self_before = copy.deepcopy(FIXTURES["self_state"])

        weak = copy.deepcopy(FIXTURES["cognitive_profile"])
        weak.update(
            {
                "engine_instance_id": "engine:c5:weak",
                "provider": "provider-a",
                "model": "weak-model",
                "reasoning_depth": 0.2,
                "planning_capacity": 0.2,
                "uncertainty_calibration": 0.3,
            }
        )
        strong = copy.deepcopy(FIXTURES["cognitive_profile"])
        strong.update(
            {
                "engine_instance_id": "engine:c5:strong",
                "provider": "provider-b",
                "model": "strong-model",
                "reasoning_depth": 0.95,
                "planning_capacity": 0.95,
                "uncertainty_calibration": 0.95,
            }
        )

        weak_state = apply_resolution(state, resolution, weak)
        strong_state = apply_resolution(state, resolution, strong)

        self.assertEqual(weak_state.state_id, strong_state.state_id)
        self.assertLess(weak_state.confidence_ceiling, strong_state.confidence_ceiling)
        self.assertTrue(weak_state.decomposition_required)
        self.assertFalse(strong_state.decomposition_required)
        self.assertEqual(FIXTURES["self_state"], self_before)
        self.assertNotIn("provider", MetacognitiveState.model_fields)
        self.assertNotIn("model", MetacognitiveState.model_fields)
        self.assertNotIn("engine_instance_id", MetacognitiveState.model_fields)

    def test_restart_roundtrip_preserves_open_prediction_and_state(self) -> None:
        prediction = self.prediction()
        state = initial_metacognitive_state(self_ref="self-state:1")

        prediction_roundtrip = PredictionRecord.model_validate_json(
            prediction.model_dump_json()
        )
        state_roundtrip = MetacognitiveState.model_validate_json(
            state.model_dump_json()
        )

        self.assertEqual(prediction, prediction_roundtrip)
        self.assertEqual(state, state_roundtrip)
        self.assertEqual(prediction_roundtrip.status, "open")

    def test_resolution_roundtrip_has_no_model_identity(self) -> None:
        prediction = self.prediction()
        resolution = resolve_prediction(
            prediction,
            self.outcome(prediction, relation="contradicts"),
        )
        restored = PredictionResolution.model_validate_json(
            resolution.model_dump_json()
        )
        self.assertEqual(resolution, restored)
        self.assertNotIn("provider", PredictionResolution.model_fields)
        self.assertNotIn("model", PredictionResolution.model_fields)

    def test_metacognition_module_has_no_executor_or_persistence_imports(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "metacognition.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            "from ..agent3",
            "MemoryStore",
            "PersonRegistry",
            "schedule_service",
            "body_session",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
