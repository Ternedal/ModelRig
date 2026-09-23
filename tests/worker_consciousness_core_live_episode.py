#!/usr/bin/env python3
"""C30-B live cognitive episode tracker tests."""
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
    CognitiveProfile,
    CognitionEvent,
    ConsciousnessCoreRuntime,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_runtime_liveness_witness,
    wake_from_unplanned_restart,
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
GOAL = "goal-" + "c" * 32
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32


def run(coro):
    return asyncio.run(coro)


def sample(marker, wall, mono, seq, epoch):
    return ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + marker * 32,
        wall_time_unix_ms=wall,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=17,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c30b:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c30b:" + marker,
    )


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


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = (
            "thinkprop-" + f"{self.calls:x}"[-1] * 32
        )
        payload["interpretation"] = "C30-B live episode."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class LiveEpisodeTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c30b",
            source_refs=["registry:test:c30b"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c30b",
            world_state_ref="world-state:c30b",
            workspace_ref="workspace:c30b",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30b"],
            ),
            active_goal_refs=[GOAL],
        )

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c30b",
            voice_source_ref="voice:c30b",
            registry_source_ref="registry:c30b",
            production_activation=False,
        )

    def wake(self, state):
        witness = build_runtime_liveness_witness(
            state=state,
            anchor=anchor("1", 111_000, 50_000, 8, EPOCH_A),
            source_ref="self-state-checkpoint-receipt:" + "d" * 64,
        )
        return wake_from_unplanned_restart(
            wake_anchor=anchor("2", 121_000, 200, 1, EPOCH_B),
            self_id=state.self_id,
            person_revision=state.person_revision,
            source_ref="sleep-wake-ack:" + "e" * 64,
            liveness_witness=witness,
        )

    def context(self, state, wake=None):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c30b",
            wake_receipt=wake,
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c30b",
            provider="mock",
            model="c30b-model",
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

    def event(self, marker, sequence, *, kind="operator_signal"):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref="event:c30b:" + marker,
            summary="C30-B explicit cognition event.",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def session(self, state, wake=None):
        engine = Engine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state, wake),
            durable_anchor_state=state,
        )
        return session, engine

    def test_idle_does_not_create_episode(self):
        state = self.durable()
        session, engine = self.session(state)

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "IDLE")
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(session.experience_episode)

    def test_first_run_opens_session_episode_with_exact_clock_sample(self):
        state = self.durable()
        session, engine = self.session(state)
        session.submit(self.event("7", 1))

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        episode = session.experience_episode
        self.assertIsNotNone(episode)
        self.assertEqual(episode.phase, "ACTIVE")
        self.assertEqual(episode.open_reason, "SESSION_START")
        self.assertEqual(episode.moment_count, 1)
        self.assertEqual(len(episode.moments), 1)

        moment = episode.moments[0]
        clock = result.supervisor_step.clock_sample
        self.assertEqual(moment.kind, "COGNITIVE_RUN")
        self.assertEqual(moment.anchor.sequence, clock.sampled_sequence)
        self.assertEqual(moment.anchor.monotonic_ms, clock.monotonic_ms)
        self.assertEqual(
            moment.anchor.runtime_epoch_id,
            clock.runtime_epoch_id,
        )
        self.assertEqual(moment.anchor.event_ref, moment.source_ref)
        self.assertTrue(
            moment.source_ref.startswith("supervisor-cycle-receipt:")
        )
        self.assertEqual(moment.active_goal_refs, [GOAL])

    def test_wake_backed_first_run_opens_post_wake_episode(self):
        state = self.durable()
        session, engine = self.session(state, self.wake(state))
        session.submit(self.event("7", 1))

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertEqual(
            session.experience_episode.open_reason,
            "POST_WAKE_RECOVERY",
        )
        self.assertEqual(session.experience_episode.moment_count, 1)
        self.assertEqual(
            session.continuity_status.status,
            "ORIENTED",
        )

    def test_later_runs_append_without_reopening_episode(self):
        state = self.durable()
        session, engine = self.session(state)

        session.submit(self.event("7", 1))
        run(session.step(profile=self.profile()))
        episode_id = session.experience_episode.episode_id
        first_source = session.experience_episode.moments[0].source_ref

        session.submit(self.event("8", 2))
        run(session.step(profile=self.profile()))

        episode = session.experience_episode
        self.assertEqual(engine.calls, 2)
        self.assertEqual(episode.episode_id, episode_id)
        self.assertEqual(episode.moment_count, 2)
        self.assertEqual(len(episode.moments), 2)
        self.assertNotEqual(
            episode.moments[1].source_ref,
            first_source,
        )
        self.assertGreater(
            episode.moments[1].anchor.sequence,
            episode.moments[0].anchor.sequence,
        )

    def test_user_turn_run_marks_user_as_participant_only_by_ref(self):
        state = self.durable()
        session, _engine = self.session(state)
        session.submit(self.event("7", 1, kind="user_turn"))

        run(session.step(profile=self.profile()))

        moment = session.experience_episode.moments[0]
        self.assertEqual(moment.participant_refs, ["actor:user"])
        payload = moment.model_dump(mode="json")
        self.assertNotIn("user_text", payload)
        self.assertNotIn("interpretation", payload)
        self.assertFalse(payload["raw_text_persisted"])
        self.assertFalse(payload["raw_chain_of_thought_persisted"])

    def test_close_clears_episode_and_continuity_orientation(self):
        state = self.durable()
        session, _engine = self.session(state, self.wake(state))
        session.submit(self.event("7", 1))
        run(session.step(profile=self.profile()))

        self.assertIsNotNone(session.experience_episode)
        self.assertIsNotNone(session.continuity_orientation)

        session.close()

        self.assertIsNone(session.experience_episode)
        self.assertIsNone(session.continuity_orientation)
        self.assertIsNone(session.recovery_completion)
        self.assertIsNone(session.continuity_state)
        self.assertEqual(session.continuity_status.status, "NONE")


if __name__ == "__main__":
    unittest.main()
