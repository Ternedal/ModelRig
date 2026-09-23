#!/usr/bin/env python3
"""C8-A embodiment observation loop tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_embodiment.py
"""
from __future__ import annotations

import copy
import inspect
import math
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    EmbodimentContractError,
    EmbodimentObservation,
    EmbodimentState,
    InferredEmbodimentState,
    MockEmbodimentObserver,
    PerformedBodyStateRef,
    SemanticBodyIntent,
    infer_embodiment_state,
    normalize_embodiment_state,
)


CYCLE = "cycle-" + "1" * 32
PERSON = "person-" + "2" * 32
PERSON_REVISION = "person-r0007"
BODY_REVISION = "body-r0003"
MOTOR_REF = "bodyrig:motor-state:77"


class ConsciousnessCoreEmbodimentTests(unittest.TestCase):
    def intent(self) -> SemanticBodyIntent:
        return SemanticBodyIntent(
            schema="kaliv-consciousness-core/semantic-body-intent/v1",
            intent_id="bintent-" + "3" * 32,
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            affect_labels=["curious", "mild_surprise"],
            intent="attentive listening",
            expressive_intensity=0.62,
            source_refs=["personality-state:1", "affect-state:1"],
            production_activation=False,
        )

    def performed(self) -> PerformedBodyStateRef:
        return PerformedBodyStateRef(
            schema="kaliv-consciousness-core/performed-body-state-ref/v1",
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            body_revision=BODY_REVISION,
            body_id_ref="bodyrig:bodyid:kaliv",
            bodycue_ref="bodyrig:bodycue:77",
            motor_state_ref=MOTOR_REF,
            motor_sequence=77,
            source_ref="bodyrig:motor-state-receipt:77",
            production_activation=False,
        )

    def observation(
        self,
        *,
        suffix: str = "4",
        sequence: int = 77,
        confidence: float = 0.95,
        kind: str = "tracking",
        values: dict | None = None,
    ) -> EmbodimentObservation:
        return EmbodimentObservation(
            schema="kaliv-consciousness-core/embodiment-observation/v1",
            observation_id="eobs-" + suffix * 32,
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            body_revision=BODY_REVISION,
            motor_state_ref=MOTOR_REF,
            renderer_ref="kaliv-vr:mock",
            observation_kind=kind,
            coordinate_space="renderer",
            observed_values=values or {"status": "ok"},
            confidence=confidence,
            source_refs=["kaliv-vr:frame:77"],
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_semantic_intent_contains_no_renderer_level_controls(self) -> None:
        fields = set(SemanticBodyIntent.model_fields)
        for forbidden in (
            "joint_angles",
            "eyebrow_percentage",
            "head_tilt_degrees",
            "blendshapes",
            "gait_phase",
            "limb_pose",
            "motor_commands",
        ):
            self.assertNotIn(forbidden, fields)

    def test_mock_loop_preserves_intended_performed_observed_separation(self) -> None:
        intent = self.intent()
        performed = self.performed()
        observations = MockEmbodimentObserver().observe(intent, performed)
        state = normalize_embodiment_state(performed, observations)

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].motor_state_ref, MOTOR_REF)
        self.assertEqual(state.performed_motor_state_ref, MOTOR_REF)
        self.assertEqual(state.person_id, PERSON)
        self.assertEqual(state.body_revision, BODY_REVISION)
        self.assertEqual(state.tracking_health, "ok")
        self.assertFalse(state.production_activation)

        self.assertNotIn("intent", EmbodimentState.model_fields)
        self.assertNotIn("observed_values", SemanticBodyIntent.model_fields)

    def test_intent_and_performed_state_require_same_cycle_and_person(self) -> None:
        observer = MockEmbodimentObserver()
        bad_cycle = self.performed().model_copy(
            update={"cycle_id": "cycle-" + "9" * 32}
        )
        with self.assertRaises(EmbodimentContractError):
            observer.observe(self.intent(), bad_cycle)

        bad_person = self.performed().model_copy(
            update={"person_id": "person-" + "9" * 32}
        )
        with self.assertRaises(EmbodimentContractError):
            observer.observe(self.intent(), bad_person)

    def test_observation_binding_mismatch_fails_closed(self) -> None:
        performed = self.performed()
        mutations = [
            {"cycle_id": "cycle-" + "8" * 32},
            {"person_id": "person-" + "8" * 32},
            {"person_revision": "person-r0008"},
            {"body_revision": "body-r0004"},
            {"motor_state_ref": "bodyrig:motor-state:other"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                observation = self.observation().model_copy(update=mutation)
                with self.assertRaises(EmbodimentContractError):
                    normalize_embodiment_state(performed, [observation])

    def test_stale_observation_fails_closed(self) -> None:
        with self.assertRaises(EmbodimentContractError):
            normalize_embodiment_state(
                self.performed(),
                [self.observation(sequence=76)],
            )

    def test_duplicate_observation_id_or_sequence_fails_closed(self) -> None:
        first = self.observation(suffix="4", sequence=77)
        duplicate_id = self.observation(suffix="4", sequence=78)
        with self.assertRaises(EmbodimentContractError):
            normalize_embodiment_state(
                self.performed(),
                [first, duplicate_id],
            )

        duplicate_sequence = self.observation(suffix="5", sequence=77)
        with self.assertRaises(EmbodimentContractError):
            normalize_embodiment_state(
                self.performed(),
                [first, duplicate_sequence],
            )

    def test_tracking_health_is_observation_derived(self) -> None:
        unavailable = normalize_embodiment_state(self.performed(), [])
        self.assertEqual(unavailable.tracking_health, "unavailable")
        self.assertEqual(unavailable.observation_confidence, 0.0)

        degraded = normalize_embodiment_state(
            self.performed(),
            [self.observation(confidence=0.30)],
        )
        self.assertEqual(degraded.tracking_health, "degraded")

        lost = normalize_embodiment_state(
            self.performed(),
            [self.observation(values={"status": "lost"}, confidence=0.95)],
        )
        self.assertEqual(lost.tracking_health, "lost")

    def test_observed_and_inferred_state_are_distinct_contracts(self) -> None:
        observation = self.observation()
        state = normalize_embodiment_state(self.performed(), [observation])
        inferred = infer_embodiment_state(
            state,
            inference_kind="action_outcome",
            proposition="the intended body action appears to have completed",
            confidence=0.8,
        )
        self.assertIsInstance(inferred, InferredEmbodimentState)
        self.assertIn(
            "embodiment-observation:" + observation.observation_id,
            inferred.evidence_observation_refs,
        )
        self.assertNotIn("proposition", EmbodimentObservation.model_fields)
        self.assertNotIn("observed_values", InferredEmbodimentState.model_fields)

    def test_inference_requires_raw_observation(self) -> None:
        state = normalize_embodiment_state(self.performed(), [])
        with self.assertRaises(EmbodimentContractError):
            infer_embodiment_state(
                state,
                inference_kind="tracking_interpretation",
                proposition="tracking seems unavailable",
                confidence=1.0,
            )

    def test_renderer_observation_cannot_author_body_or_personality(self) -> None:
        fields = set(EmbodimentObservation.model_fields)
        for forbidden in (
            "bodyprint",
            "movement_identity",
            "personality",
            "personality_revision",
            "body_identity_mutation",
            "motor_state_mutation",
        ):
            self.assertNotIn(forbidden, fields)

    def test_nonfinite_observation_value_fails_closed(self) -> None:
        payload = self.observation().model_dump(mode="json")
        payload["observed_values"] = {"x": float("nan")}
        with self.assertRaises(ValidationError):
            EmbodimentObservation.model_validate(payload)

    def test_body_identity_is_independent_of_thought_engine(self) -> None:
        signature = inspect.signature(normalize_embodiment_state)
        self.assertNotIn("model", signature.parameters)
        self.assertNotIn("provider", signature.parameters)
        self.assertNotIn("cognitive_profile", signature.parameters)

        before = self.performed()
        first = normalize_embodiment_state(before, [self.observation()])
        second = normalize_embodiment_state(before, [self.observation()])
        self.assertEqual(first, second)
        self.assertEqual(first.person_id, before.person_id)
        self.assertEqual(first.body_revision, before.body_revision)

    def test_embodiment_contracts_have_no_action_authority(self) -> None:
        for model in (
            SemanticBodyIntent,
            EmbodimentObservation,
            EmbodimentState,
            InferredEmbodimentState,
        ):
            fields = set(model.model_fields)
            self.assertNotIn("actions", fields)
            self.assertNotIn("tools", fields)
            self.assertNotIn("execute", fields)
            self.assertNotIn("issue_bodycue", fields)

    def test_c8a_has_no_bodyrig_mutation_or_runtime_import(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "embodiment.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "BodyRigClient",
            "body_session",
            "motor_state_store",
            "issue_bodycue",
            "requests.",
            "httpx.",
            "import sqlite3",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
