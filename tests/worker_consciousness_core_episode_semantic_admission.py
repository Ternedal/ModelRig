#!/usr/bin/env python3
"""C30-D memory, embodiment and prediction episode admission tests."""
from __future__ import annotations

import copy
import hashlib
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
    MemoryContextSnapshot,
    PerformedBodyStateRef,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
    infer_embodiment_state,
    normalize_embodiment_state,
    prediction_from_proposal,
)
from app.consciousness_core.metacognition import (  # noqa: E402
    OutcomeObservation,
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

SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
BODY_REV = "body-r0003"
CYCLE = "cycle-" + "1" * 32
MOTOR_REF = "bodyrig:motor:c30d"


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        return payload


class CountingClock(TrustedRuntimeClock):
    def __init__(self):
        self.calls = 0
        wall = iter(
            1_700_000_000_000_000_000 + i * 1_000_000_000
            for i in range(1, 128)
        )
        mono = iter(i * 1_000_000_000 for i in range(1, 128))
        super().__init__(
            wall_time_ns=lambda: next(wall),
            monotonic_ns=lambda: next(mono),
        )

    def sample(self):
        self.calls += 1
        return super().sample()


class EpisodeSemanticAdmissionTests(unittest.TestCase):
    def session(self):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id=SELF,
            revision=200,
            person_id=PERSON,
            person_revision=PERSON_REV,
            personality_state_ref="personality-state:c30d",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=["goal-" + "9" * 32],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30d"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=PERSON,
            person_revision=PERSON_REV,
            body_revision=BODY_REV,
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c30d",
            voice_source_ref="voice:c30d",
            registry_source_ref="registry:c30d",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:c30d",
        )
        engine = Engine()
        clock = CountingClock()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=clock,
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            engine,
            clock,
        )

    def memory_snapshot(self, *, empty=False):
        context = "" if empty else "PRIVATE-C30D-MEMORY-CONTEXT"
        included = [] if empty else ["memory-private-c30d"]
        encoded = context.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return MemoryContextSnapshot(
            schema="kaliv-consciousness-core/memory-context-snapshot/v1",
            target="local",
            context=context,
            included_ids=included,
            context_sha256=digest,
            character_count=len(context),
            byte_count=len(encoded),
            authority="reference_data",
            sent_to_model=False,
            source_ref=f"memory4-context:{digest}",
            production_activation=False,
        )

    def performed(self):
        return PerformedBodyStateRef(
            schema="kaliv-consciousness-core/performed-body-state-ref/v1",
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REV,
            body_revision=BODY_REV,
            body_id_ref="bodyrig:body:c30d",
            bodycue_ref="bodyrig:bodycue:c30d",
            motor_state_ref=MOTOR_REF,
            motor_sequence=44,
            source_ref="bodyrig:motor-receipt:c30d",
            production_activation=False,
        )

    def observation(self):
        return EmbodimentObservation(
            schema="kaliv-consciousness-core/embodiment-observation/v1",
            observation_id="eobs-" + "2" * 32,
            cycle_id=CYCLE,
            person_id=PERSON,
            person_revision=PERSON_REV,
            body_revision=BODY_REV,
            motor_state_ref=MOTOR_REF,
            renderer_ref="kaliv-vr:c30d",
            observation_kind="tracking",
            coordinate_space="renderer",
            observed_values={"status": "ok", "performed": True},
            confidence=0.95,
            source_refs=["kaliv-vr:frame:c30d"],
            observed_sequence=45,
            production_activation=False,
        )

    def embodiment_state(self):
        return normalize_embodiment_state(
            self.performed(),
            [self.observation()],
        )

    def inference(self, kind="interaction_result"):
        return infer_embodiment_state(
            self.embodiment_state(),
            inference_kind=kind,
            proposition="PRIVATE-C30D-EMBODIMENT-PROPOSITION",
            confidence=0.8,
        )

    def prediction(self):
        return prediction_from_proposal(
            copy.deepcopy(FIXTURES["thought_request"]),
            copy.deepcopy(FIXTURES["thought_proposal"]),
            outcome_index=0,
            subject_ref="system:modelrig",
            expected_observation_kind="tool_result",
            source_refs=["cycle:evidence:c30d"],
        )

    def outcome(self, prediction, relation="contradicts"):
        return OutcomeObservation(
            schema="kaliv-consciousness-core/outcome-observation/v1",
            outcome_id="out-" + "7" * 32,
            prediction_id=prediction.prediction_id,
            observed_proposition="PRIVATE-C30D-PREDICTION-OUTCOME",
            observation_kind="tool_result",
            prediction_relation=relation,
            source_refs=["tool-receipt:c30d"],
            confidence=1.0,
            observed_sequence=51,
            production_activation=False,
        )

    def test_empty_memory_recall_is_episode_and_clock_noop(self):
        session, engine, clock = self.session()
        clock_before = clock.calls

        result = session.submit_memory_recall(
            self.memory_snapshot(empty=True)
        )

        self.assertFalse(result.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before)
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(session.experience_episode)

    def test_memory_recall_reuses_attention_clock_and_replay_adds_no_moment(self):
        session, engine, clock = self.session()
        snapshot = self.memory_snapshot()
        clock_before = clock.calls

        first = session.submit_memory_recall(snapshot)

        self.assertTrue(first.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before + 1)
        self.assertEqual(engine.calls, 0)
        episode = session.experience_episode
        self.assertEqual(episode.moment_count, 1)
        moment = episode.moments[0]
        self.assertEqual(moment.kind, "MEMORY_RECALL")
        self.assertEqual(
            moment.source_ref,
            first.plan.cognition_event.source_ref,
        )
        self.assertEqual(
            moment.anchor.sequence,
            first.plan.cognition_event.observed_sequence,
        )
        encoded = episode.model_dump_json()
        self.assertNotIn(snapshot.context, encoded)
        self.assertNotIn(snapshot.included_ids[0], encoded)

        before = session.experience_episode
        calls = clock.calls
        second = session.submit_memory_recall(snapshot)

        self.assertEqual(second.plan, first.plan)
        self.assertEqual(clock.calls, calls)
        self.assertEqual(session.experience_episode, before)

    def test_gaze_no_event_is_episode_noop(self):
        session, engine, clock = self.session()
        state = self.embodiment_state()
        clock_before = clock.calls

        result = session.submit_embodiment_inference(
            state=state,
            inference=self.inference("gaze_state"),
        )

        self.assertFalse(result.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before)
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(session.experience_episode)

    def test_semantic_embodiment_change_adds_reference_only_moment(self):
        session, engine, clock = self.session()
        state = self.embodiment_state()
        inference = self.inference()
        clock_before = clock.calls

        first = session.submit_embodiment_inference(
            state=state,
            inference=inference,
        )

        self.assertTrue(first.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before + 1)
        self.assertEqual(engine.calls, 0)
        moment = session.experience_episode.moments[0]
        self.assertEqual(moment.kind, "EMBODIMENT_CHANGE")
        self.assertEqual(
            moment.source_ref,
            first.plan.cognition_event.source_ref,
        )
        self.assertNotIn(
            inference.proposition,
            session.experience_episode.model_dump_json(),
        )

        before = session.experience_episode
        second = session.submit_embodiment_inference(
            state=state,
            inference=inference,
        )
        self.assertEqual(
            second.supervisor_revision_before,
            second.supervisor_revision_after,
        )
        self.assertEqual(session.experience_episode, before)

    def test_non_mismatch_prediction_is_episode_noop(self):
        session, engine, clock = self.session()
        prediction = self.prediction()
        clock_before = clock.calls

        result = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=self.outcome(prediction, relation="supports"),
        )

        self.assertFalse(result.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before)
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(session.experience_episode)

    def test_prediction_mismatch_adds_reference_only_moment(self):
        session, engine, clock = self.session()
        prediction = self.prediction()
        outcome = self.outcome(prediction)
        clock_before = clock.calls

        first = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )

        self.assertTrue(first.cognition_event_admitted)
        self.assertEqual(clock.calls, clock_before + 1)
        self.assertEqual(engine.calls, 0)
        moment = session.experience_episode.moments[0]
        self.assertEqual(moment.kind, "PREDICTION_RESOLUTION")
        self.assertEqual(
            moment.source_ref,
            first.plan.cognition_event.source_ref,
        )
        self.assertNotIn(
            outcome.observed_proposition,
            session.experience_episode.model_dump_json(),
        )

        before = session.experience_episode
        second = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )
        self.assertEqual(
            second.supervisor_revision_before,
            second.supervisor_revision_after,
        )
        self.assertEqual(session.experience_episode, before)

    def test_mixed_semantic_moments_share_one_temporally_ordered_episode(self):
        session, engine, _clock = self.session()

        memory = session.submit_memory_recall(self.memory_snapshot())
        embodiment = session.submit_embodiment_inference(
            state=self.embodiment_state(),
            inference=self.inference(),
        )
        prediction = self.prediction()
        mismatch = session.submit_prediction_outcome(
            prediction=prediction,
            outcome=self.outcome(prediction),
        )

        self.assertEqual(engine.calls, 0)
        self.assertTrue(memory.cognition_event_admitted)
        self.assertTrue(embodiment.cognition_event_admitted)
        self.assertTrue(mismatch.cognition_event_admitted)
        episode = session.experience_episode
        self.assertEqual(episode.moment_count, 3)
        self.assertEqual(
            [item.kind for item in episode.moments],
            [
                "MEMORY_RECALL",
                "EMBODIMENT_CHANGE",
                "PREDICTION_RESOLUTION",
            ],
        )
        self.assertEqual(
            [item.anchor.sequence for item in episode.moments],
            sorted(
                item.anchor.sequence for item in episode.moments
            ),
        )
        self.assertEqual(
            episode.moments[0].active_goal_refs,
            ["goal-" + "9" * 32],
        )


if __name__ == "__main__":
    unittest.main()
