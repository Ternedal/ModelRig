#!/usr/bin/env python3
"""C30-C world/user event admission into the live experiential episode."""
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
    WorldEvidenceEvent,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_runtime_liveness_witness,
    wake_from_unplanned_restart,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
    SupervisorLifecycleError,
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
        source_ref="trusted:c30c:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c30c:" + marker,
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
        payload["interpretation"] = "C30-C event admission."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class EpisodeEventAdmissionTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c30c",
            source_refs=["registry:test:c30c"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c30c",
            world_state_ref="world-state:c30c",
            workspace_ref="workspace:c30c",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30c"],
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
            body_source_ref="body:c30c",
            voice_source_ref="voice:c30c",
            registry_source_ref="registry:c30c",
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
            bootstrap_source_ref="runtime:c30c",
            wake_receipt=wake,
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c30c",
            provider="mock",
            model="c30c-model",
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

    def session(self, state, wake=None):
        engine = Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )
        session = ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=self.context(state, wake),
            durable_anchor_state=state,
        )
        return session, engine, bridge

    def evidence(self, marker="7", sequence=1):
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + marker * 32,
            subject_ref="world:test",
            proposition="A bounded observed world change.",
            confidence=1.0,
            epistemic_status="observed",
            source_refs=["sensor:c30c:" + marker],
            observed_sequence=sequence,
            production_activation=False,
        )

    def cognition_event(self, marker, sequence):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="operator_signal",
            source_ref="operator:c30c:" + marker,
            summary="Explicit C30-C follow-up cognition.",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_new_world_evidence_opens_episode_without_model_call(self):
        state = self.durable()
        session, engine, _bridge = self.session(state)

        result = session.submit_world_evidence(
            self.evidence(),
            attention_salience=0.7,
        )

        self.assertEqual(engine.calls, 0)
        self.assertTrue(result.cognition_event_queued)
        episode = session.experience_episode
        self.assertIsNotNone(episode)
        self.assertEqual(episode.open_reason, "SESSION_START")
        self.assertEqual(episode.moment_count, 1)
        moment = episode.moments[0]
        self.assertEqual(moment.kind, "WORLD_EVIDENCE")
        self.assertEqual(moment.source_ref, result.evidence_ref)
        self.assertEqual(moment.anchor.event_ref, result.evidence_ref)
        self.assertEqual(moment.salience, 0.7)
        self.assertEqual(moment.active_goal_refs, [GOAL])
        self.assertEqual(
            moment.anchor.runtime_epoch_id,
            session.supervisor_state.runtime_epoch_id,
        )

    def test_world_replay_adds_no_moment_and_no_new_episode_state(self):
        state = self.durable()
        session, engine, _bridge = self.session(state)
        evidence = self.evidence()

        first = session.submit_world_evidence(
            evidence,
            attention_salience=0.7,
        )
        before = session.experience_episode
        before_ref = before.model_dump(mode="json")

        replay = session.submit_world_evidence(
            evidence,
            attention_salience=0.7,
        )

        self.assertEqual(engine.calls, 0)
        self.assertTrue(replay.world_transition.idempotent_replay)
        self.assertFalse(replay.cognition_event_queued)
        self.assertEqual(
            session.experience_episode.model_dump(mode="json"),
            before_ref,
        )
        self.assertEqual(
            session.experience_episode.moment_count,
            first.live_state.completed_cycles + 1,
        )

    def test_reported_user_turn_is_reference_only_episode_moment(self):
        state = self.durable()
        session, engine, _bridge = self.session(state)

        result = session.submit_reported_user_turn(
            turn_id="turn-c30c-1",
            user_text="This text must stay in WorldState, not the episode.",
            source_ref="chat-turn:c30c:1",
        )

        self.assertEqual(engine.calls, 0)
        moment = session.experience_episode.moments[0]
        self.assertEqual(moment.kind, "USER_TURN")
        self.assertEqual(moment.source_ref, result.evidence_ref)
        self.assertEqual(moment.participant_refs, ["actor:user"])
        payload = moment.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("This text must stay", encoded)
        self.assertNotIn("user_text", encoded)
        self.assertFalse(moment.raw_text_persisted)
        self.assertFalse(moment.raw_chain_of_thought_persisted)

    def test_wake_pre_run_event_opens_reorientation_episode(self):
        state = self.durable()
        session, engine, _bridge = self.session(state, self.wake(state))

        session.submit_reported_user_turn(
            turn_id="turn-c30c-wake",
            user_text="A first post-wake turn.",
            source_ref="chat-turn:c30c:wake",
        )

        self.assertEqual(engine.calls, 0)
        self.assertEqual(
            session.continuity_status.status,
            "REORIENTING",
        )
        self.assertEqual(
            session.experience_episode.open_reason,
            "WAKE_REORIENTATION",
        )
        episode_id = session.experience_episode.episode_id

        session.submit(self.cognition_event("8", 2))
        step = run(session.step(profile=self.profile()))

        self.assertEqual(step.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertEqual(
            session.experience_episode.episode_id,
            episode_id,
        )
        self.assertEqual(
            session.experience_episode.moment_count,
            2,
        )
        self.assertEqual(
            [item.kind for item in session.experience_episode.moments],
            ["USER_TURN", "COGNITIVE_RUN"],
        )
        self.assertEqual(
            session.continuity_status.status,
            "ORIENTED",
        )

    def test_bridge_rejection_does_not_publish_prospective_episode(self):
        state = self.durable()
        session, engine, bridge = self.session(state)
        before_live = session.live_state.model_dump(mode="json")
        bridge.close()

        with self.assertRaises(SupervisorLifecycleError):
            session.submit_world_evidence(
                self.evidence(),
                attention_salience=0.7,
            )

        self.assertEqual(engine.calls, 0)
        self.assertIsNone(session.experience_episode)
        self.assertEqual(
            session.live_state.model_dump(mode="json"),
            before_live,
        )


if __name__ == "__main__":
    unittest.main()
