#!/usr/bin/env python3
"""C26-B prediction-mismatch attention admission tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_prediction_attention.py
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
    new_automatic_cognition_accounting,
    evaluate_autonomous_trigger,
    prediction_from_proposal,
)
from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
)
from app.consciousness_core.metacognition import (  # noqa: E402
    OutcomeObservation,
)
from app.consciousness_core.prediction_attention import (  # noqa: E402
    PredictionAttentionError,
    admit_prediction_outcome if False else plan_prediction_outcome,
    outcome_observation_ref,
    prediction_attention_ref,
    prediction_resolution_ref,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        return payload


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 16)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 16))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class PredictionAttentionTests(unittest.TestCase):
    def prediction(self):
        request = copy.deepcopy(FIXTURES["thought_request"])
        proposal = copy.deepcopy(FIXTURES["thought_proposal"])
        return prediction_from_proposal(
            request,
            proposal,
            outcome_index=0,
            subject_ref="system:modelrig",
            expected_observation_kind="tool_result",
            source_refs=["cycle:evidence:c26b"],
        )

    def outcome(self, prediction, relation="contradicts", sequence=11):
        return OutcomeObservation(
            schema="kaliv-consciousness-core/outcome-observation/v1",
            outcome_id="out-" + "7" * 32,
            prediction_id=prediction.prediction_id,
            observed_proposition="Observed structured outcome.",
            observation_kind="tool_result",
            prediction_relation=relation,
            source_refs=["tool-receipt:c26b"],
            confidence=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def session(self):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=90,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:c26b",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=[],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["test:c26b"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c26b",
            voice_source_ref="voice:c26b",
            registry_source_ref="registry:c26b",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:c26b",
        )
        engine = Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            engine,
        )

    def test_exact_mismatch_creates_deterministic_prediction_error(self):
        prediction = self.prediction()
        outcome = self.outcome(prediction)
        first = plan_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )
        second = plan_prediction_outcome(
            prediction=prediction.model_dump(mode="json"),
            outcome=outcome.model_dump(mode="json"),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.resolution.result, "mismatch")
        self.assertEqual(first.resolution.error_score, 1.0)
        self.assertIsNotNone(first.cognition_event)
        self.assertEqual(first.cognition_event.kind, "prediction_error")
        self.assertEqual(first.cognition_event.salience, 1.0)
        self.assertEqual(
            first.cognition_event.observed_sequence,
            outcome.observed_sequence,
        )
        self.assertEqual(
            first.resolution_ref,
            prediction_resolution_ref(first.resolution),
        )
        self.assertEqual(first.outcome_ref, outcome_observation_ref(outcome))
        self.assertEqual(
            first.cognition_event.source_ref,
            prediction_attention_ref(
                resolution=first.resolution,
                outcome=outcome,
            ),
        )

    def test_non_mismatch_relations_create_no_cognition_event(self):
        prediction = self.prediction()
        expectations = {
            "supports": "match",
            "partially_supports": "partial",
            "unknown": "indeterminate",
        }
        for relation, expected in expectations.items():
            with self.subTest(relation=relation):
                plan = plan_prediction_outcome(
                    prediction=prediction,
                    outcome=self.outcome(prediction, relation=relation),
                )
                self.assertEqual(plan.resolution.result, expected)
                self.assertIsNone(plan.cognition_event)
                self.assertEqual(plan.model_calls, 0)

    def test_session_admits_mismatch_without_changing_live_state_or_model(self):
        session, engine = self.session()
        prediction = self.prediction()
        outcome = self.outcome(prediction)
        live_before = session.live_state
        supervisor_before = session.supervisor_state

        receipt = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )

        self.assertTrue(receipt.cognition_event_admitted)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(session.live_state, live_before)
        self.assertEqual(
            receipt.supervisor_revision_before,
            supervisor_before.revision,
        )
        self.assertEqual(
            receipt.supervisor_revision_after,
            supervisor_before.revision + 1,
        )
        self.assertEqual(len(session.supervisor_state.pending_events), 1)
        event = session.supervisor_state.pending_events[0]
        self.assertEqual(event.kind, "prediction_error")
        self.assertEqual(event, receipt.plan.cognition_event)

    def test_exact_duplicate_mismatch_is_idempotent(self):
        session, engine = self.session()
        prediction = self.prediction()
        outcome = self.outcome(prediction)

        first = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )
        revision = session.supervisor_state.revision
        second = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )

        self.assertTrue(first.cognition_event_admitted)
        self.assertTrue(second.cognition_event_admitted)
        self.assertEqual(second.supervisor_revision_before, revision)
        self.assertEqual(second.supervisor_revision_after, revision)
        self.assertEqual(len(session.supervisor_state.pending_events), 1)
        self.assertEqual(engine.calls, 0)

    def test_non_mismatch_is_supervisor_noop(self):
        session, engine = self.session()
        prediction = self.prediction()
        before = session.supervisor_state
        receipt = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=self.outcome(prediction, relation="supports"),
        )
        self.assertFalse(receipt.cognition_event_admitted)
        self.assertEqual(
            receipt.supervisor_revision_before,
            before.revision,
        )
        self.assertEqual(
            receipt.supervisor_revision_after,
            before.revision,
        )
        self.assertEqual(session.supervisor_state.pending_events, [])
        self.assertEqual(engine.calls, 0)

    def test_wrong_prediction_binding_fails_before_queue(self):
        session, engine = self.session()
        prediction = self.prediction()
        outcome = self.outcome(prediction).model_copy(
            update={"prediction_id": "pred-" + "9" * 32}
        )
        before = session.supervisor_state
        with self.assertRaises(Exception):
            session.submit_prediction_outcome(
                prediction=prediction,
                outcome=outcome,
            )
        self.assertEqual(session.supervisor_state, before)
        self.assertEqual(engine.calls, 0)

    def test_mismatch_event_is_eligible_under_default_c25a_policy(self):
        prediction = self.prediction()
        plan = plan_prediction_outcome(
            prediction=prediction,
            outcome=self.outcome(prediction),
        )
        event = plan.cognition_event
        self.assertIsNotNone(event)

        clock = deterministic_clock().sample()
        accounting = new_automatic_cognition_accounting(clock)
        decision = evaluate_autonomous_trigger(
            event=event,
            clock=clock,
            accounting=accounting,
            policy=DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
        )
        self.assertEqual(decision.decision, "ELIGIBLE")
        self.assertEqual(decision.reason, "eligible")
        self.assertEqual(decision.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
