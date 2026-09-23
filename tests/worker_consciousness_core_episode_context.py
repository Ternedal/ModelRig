#!/usr/bin/env python3
"""C30-E bounded current-episode model-context tests."""
from __future__ import annotations

import asyncio
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
    ClockSample,
    CognitiveCycleCoordinator,
    CognitiveProfile,
    CognitionEvent,
    ConsciousnessCoreRuntime,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    append_episode_moment,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_episode_moment,
    open_experience_episode,
    project_episode_context,
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
EPOCH = "epoch-" + "1" * 32


def run(coro):
    return asyncio.run(coro)


def clock_anchor(sequence: int, *, event_ref: str):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + f"{sequence:032x}",
        wall_time_unix_ms=1_700_000_000_000 + sequence * 1000,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=17,
        monotonic_ms=sequence * 1000,
        runtime_epoch_id=EPOCH,
        sampled_sequence=sequence,
        source_ref=f"trusted:c30e:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 128)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 128))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class CaptureEngine:
    def __init__(self):
        self.calls = 0
        self.contexts = []

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.contexts.append(copy.deepcopy(context))
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = (
            "thinkprop-" + f"{self.calls:x}"[-1] * 32
        )
        payload["interpretation"] = "C30-E bounded episode context."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class EpisodeContextTests(unittest.TestCase):
    def durable(self, *, self_id=SELF, person_id=PERSON):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=self_id,
            person_id=person_id,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c30e",
            source_refs=["registry:test:c30e"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c30e",
            world_state_ref="world-state:c30e",
            workspace_ref="workspace:c30e",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30e"],
            ),
            active_goal_refs=["goal-" + "9" * 32],
        )

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c30e",
            voice_source_ref="voice:c30e",
            registry_source_ref="registry:c30e",
            production_activation=False,
        )

    def context(self, state):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c30e",
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c30e",
            provider="mock",
            model="c30e-model",
            reasoning_depth=0.8,
            planning_capacity=0.8,
            context_capacity_tokens=8192,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.9,
            ephemeral=True,
            identity_authority=False,
            persistent_state_authority=False,
            action_authority=False,
            production_activation=False,
        )

    def session(self, state):
        engine = CaptureEngine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state),
            durable_anchor_state=state,
        )
        return session, engine

    def operator_event(self, marker, sequence):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="operator_signal",
            source_ref="operator:c30e:" + marker,
            summary="Explicit C30-E cognition event.",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_projection_caps_recent_moments_and_elapsed_time(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=clock_anchor(
                1,
                event_ref="episode-open:c30e",
            ),
            reason="SESSION_START",
        )
        for sequence in range(1, 21):
            source_ref = "event:c30e:" + f"{sequence:04d}"
            episode = append_episode_moment(
                episode,
                build_episode_moment(
                    kind="WORLD_EVIDENCE",
                    source_ref=source_ref,
                    anchor=clock_anchor(
                        sequence,
                        event_ref=source_ref,
                    ),
                    salience=0.5,
                ),
            )

        projection = project_episode_context(episode)

        self.assertEqual(projection.total_moment_count, 20)
        self.assertEqual(projection.evicted_moment_count, 0)
        self.assertEqual(projection.retained_moment_count, 20)
        self.assertEqual(len(projection.recent_moments), 16)
        self.assertEqual(
            projection.recent_moments[0].temporal_sequence,
            5,
        )
        self.assertEqual(
            projection.recent_moments[-1].temporal_sequence,
            20,
        )
        self.assertEqual(projection.objective_elapsed_ms, 19_000)
        self.assertFalse(projection.raw_text_included)
        self.assertFalse(projection.raw_chain_of_thought_included)
        self.assertFalse(projection.identity_authority)
        self.assertFalse(projection.execution_authority)

    def test_first_run_without_episode_preserves_old_context_shape(self):
        state = self.durable()
        session, engine = self.session(state)
        session.submit(self.operator_event("7", 1))

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertNotIn("episode", engine.contexts[0])
        self.assertIsNotNone(session.experience_episode)
        self.assertEqual(session.experience_episode.moment_count, 1)

    def test_user_turn_episode_reaches_first_model_without_user_text(self):
        state = self.durable()
        session, engine = self.session(state)
        sentinel = "PRIVATE-C30E-USER-TEXT-SENTINEL"

        admission = session.submit_reported_user_turn(
            turn_id="turn-c30e-1",
            user_text=sentinel,
            source_ref="chat-turn:c30e:1",
        )
        self.assertTrue(admission.cognition_event_queued)

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        projection = engine.contexts[0]["episode"]
        self.assertEqual(projection["phase"], "ACTIVE")
        self.assertEqual(projection["open_reason"], "SESSION_START")
        self.assertEqual(projection["total_moment_count"], 1)
        self.assertEqual(
            projection["recent_moments"][0]["kind"],
            "USER_TURN",
        )
        self.assertEqual(
            projection["recent_moments"][0]["participant_refs"],
            ["actor:user"],
        )
        encoded = json.dumps(projection, sort_keys=True)
        self.assertNotIn(sentinel, encoded)
        self.assertNotIn("user_text", encoded)
        self.assertNotIn("context", projection)
        self.assertFalse(projection["raw_text_included"])
        self.assertFalse(
            projection["raw_chain_of_thought_included"]
        )

    def test_second_run_sees_prior_cognitive_run_episode(self):
        state = self.durable()
        session, engine = self.session(state)

        session.submit(self.operator_event("7", 1))
        run(session.step(profile=self.profile()))
        self.assertEqual(engine.calls, 1)
        self.assertNotIn("episode", engine.contexts[0])

        session.submit(self.operator_event("8", 2))
        second = run(session.step(profile=self.profile()))

        self.assertEqual(second.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 2)
        projection = engine.contexts[1]["episode"]
        self.assertEqual(projection["total_moment_count"], 1)
        self.assertEqual(
            projection["recent_moments"][0]["kind"],
            "COGNITIVE_RUN",
        )
        self.assertTrue(
            projection["recent_moments"][0]["source_ref"].startswith(
                "supervisor-cycle-receipt:"
            )
        )

    def test_foreign_episode_fails_before_model_call(self):
        state = self.durable()
        context = self.context(state)
        foreign = open_experience_episode(
            self_id="self-" + "f" * 32,
            person_revision=PERSON_REV,
            opening_anchor=clock_anchor(
                1,
                event_ref="episode-open:foreign",
            ),
            reason="SESSION_START",
        )
        engine = CaptureEngine()
        cycle = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(engine)
        )

        with self.assertRaisesRegex(
            Exception,
            "experience episode belongs to another self",
        ):
            run(
                cycle.run(
                    state=context.state,
                    world=context.world,
                    workspace=context.workspace,
                    personality_snapshot=context.personality_snapshot,
                    profile=self.profile(),
                    experience_episode=foreign,
                )
            )

        self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
