#!/usr/bin/env python3
"""C26-D semantic embodiment-change attention tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_embodiment_attention.py
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
    ConsciousnessCoreRuntime,
    EmbodimentObservation,
    PerformedBodyStateRef,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
    evaluate_autonomous_trigger,
    infer_embodiment_state,
    new_automatic_cognition_accounting,
    normalize_embodiment_state,
)
from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
)
from app.consciousness_core.embodiment_attention import (  # noqa: E402
    EmbodimentAttentionError,
    embodiment_inference_ref,
    embodiment_state_ref,
    plan_embodiment_attention,
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

CYCLE = "cycle-" + "1" * 32
PERSON = "person-" + "b" * 32
PERSON_REVISION = "person-r0007"
BODY_REVISION = "body-r0003"
MOTOR_REF = "bodyrig:motor:c26d"


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
        for i in range(1, 24)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 24))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class EmbodimentAttentionTests(unittest.TestCase):
    def performed(self):
        return PerformedBodyStateRef(
            schema="kaliv-consciousness-core/performed-body-state-ref/v1",
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            body_revision=BODY_REVISION,
            body_id_ref="bodyrig:body:c26d",
            bodycue_ref="bodyrig:bodycue:c26d",
            motor_state_ref=MOTOR_REF,
            motor_sequence=44,
            source_ref="bodyrig:motor-receipt:c26d",
            production_activation=False,
        )

    def observation(self):
        return EmbodimentObservation(
            schema="kaliv-consciousness-core/embodiment-observation/v1",
            observation_id="eobs-" + "2" * 32,
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            body_revision=BODY_REVISION,
            motor_state_ref=MOTOR_REF,
            renderer_ref="kaliv-vr:c26d",
            observation_kind="tracking",
            coordinate_space="renderer",
            observed_values={"status": "ok", "performed": True},
            confidence=0.95,
            source_refs=["kaliv-vr:frame:c26d"],
            observed_sequence=45,
            production_activation=False,
        )

    def embodiment_state(self):
        return normalize_embodiment_state(
            self.performed(),
            [self.observation()],
        )

    def inference(self, kind="action_outcome", proposition="Action completed."):
        return infer_embodiment_state(
            self.embodiment_state(),
            inference_kind=kind,
            proposition=proposition,
            confidence=0.8,
        )

    def session(self):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=170,
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            personality_state_ref="personality-state:c26d",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=[],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["test:c26d"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=PERSON,
            person_revision=PERSON_REVISION,
            body_revision=BODY_REVISION,
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c26d",
            voice_source_ref="voice:c26d",
            registry_source_ref="registry:c26d",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:c26d",
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

    def test_meaningful_semantic_kinds_create_fixed_salience_events(self):
        expectations = {
            "action_outcome": 0.90,
            "reachability": 0.90,
            "locomotion_blocked": 1.00,
            "interaction_result": 0.95,
            "tracking_interpretation": 0.95,
        }
        state = self.embodiment_state()
        for kind, salience in expectations.items():
            with self.subTest(kind=kind):
                inference = infer_embodiment_state(
                    state,
                    inference_kind=kind,
                    proposition=f"Semantic inference {kind}.",
                    confidence=0.8,
                )
                plan = plan_embodiment_attention(
                    state=state,
                    inference=inference,
                )
                self.assertIsNotNone(plan.cognition_event)
                event = plan.cognition_event
                self.assertEqual(event.kind, "embodiment_change")
                self.assertEqual(event.salience, salience)
                self.assertEqual(
                    event.observed_sequence,
                    state.last_observed_sequence,
                )
                self.assertEqual(
                    plan.embodiment_state_ref,
                    embodiment_state_ref(state),
                )
                self.assertEqual(
                    plan.inference_ref,
                    embodiment_inference_ref(inference),
                )

    def test_gaze_state_is_deliberately_not_admitted(self):
        state = self.embodiment_state()
        inference = infer_embodiment_state(
            state,
            inference_kind="gaze_state",
            proposition="Gaze changed.",
            confidence=0.9,
        )
        plan = plan_embodiment_attention(
            state=state,
            inference=inference,
        )
        self.assertIsNone(plan.cognition_event)
        self.assertEqual(plan.model_calls, 0)

    def test_evidence_or_identity_drift_fails_closed(self):
        state = self.embodiment_state()
        inference = self.inference()

        bad_evidence = inference.model_copy(
            update={"evidence_observation_refs": ["embodiment-observation:other"]}
        )
        with self.assertRaises(EmbodimentAttentionError):
            plan_embodiment_attention(
                state=state,
                inference=bad_evidence,
            )

        bad_person = inference.model_copy(
            update={"person_id": "person-" + "9" * 32}
        )
        with self.assertRaises(EmbodimentAttentionError):
            plan_embodiment_attention(
                state=state,
                inference=bad_person,
            )

    def test_summary_is_bounded_at_contract_limit(self):
        state = self.embodiment_state()
        inference = infer_embodiment_state(
            state,
            inference_kind="interaction_result",
            proposition="x" * 2048,
            confidence=0.8,
        )
        plan = plan_embodiment_attention(
            state=state,
            inference=inference,
        )
        self.assertIsNotNone(plan.cognition_event)
        self.assertLessEqual(len(plan.cognition_event.summary), 2048)

    def test_session_admits_event_without_live_state_or_model_mutation(self):
        session, engine = self.session()
        state = self.embodiment_state()
        inference = self.inference()
        live_before = session.live_state
        supervisor_before = session.supervisor_state

        receipt = session.submit_embodiment_inference(
            state=state,
            inference=inference,
        )

        self.assertTrue(receipt.cognition_event_admitted)
        self.assertFalse(receipt.body_mutation_authority)
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

    def test_exact_replay_is_idempotent(self):
        session, engine = self.session()
        state = self.embodiment_state()
        inference = self.inference()

        first = session.submit_embodiment_inference(
            state=state,
            inference=inference,
        )
        revision = session.supervisor_state.revision
        second = session.submit_embodiment_inference(
            state=state,
            inference=inference,
        )

        self.assertEqual(first.plan, second.plan)
        self.assertEqual(second.supervisor_revision_before, revision)
        self.assertEqual(second.supervisor_revision_after, revision)
        self.assertEqual(len(session.supervisor_state.pending_events), 1)
        self.assertEqual(engine.calls, 0)

    def test_session_rejects_other_live_person_before_queue(self):
        session, engine = self.session()
        state = self.embodiment_state().model_copy(
            update={"person_id": "person-" + "8" * 32}
        )
        inference = self.inference().model_copy(
            update={"person_id": "person-" + "8" * 32}
        )
        before = session.supervisor_state
        with self.assertRaises(Exception):
            session.submit_embodiment_inference(
                state=state,
                inference=inference,
            )
        self.assertEqual(session.supervisor_state, before)
        self.assertEqual(engine.calls, 0)

    def test_embodiment_event_is_eligible_under_default_c25a_policy(self):
        state = self.embodiment_state()
        plan = plan_embodiment_attention(
            state=state,
            inference=self.inference("interaction_result"),
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
