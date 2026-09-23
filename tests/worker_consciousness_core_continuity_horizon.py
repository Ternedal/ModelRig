#!/usr/bin/env python3
"""C29-I one-successful-RUN continuity horizon tests."""
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
    ContinuityHorizonError,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_runtime_liveness_witness,
    consume_continuity_reorientation_window,
    open_continuity_reorientation_window,
    prepare_sleep,
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
        local_hour=10,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c29i:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29i:" + marker,
    )


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 96)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 96))
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
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "C29-I horizon."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class ContinuityHorizonTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29i",
            source_refs=["registry:test:c29i"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29i",
            world_state_ref="world-state:c29i",
            workspace_ref="workspace:c29i",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29i"],
            ),
        )
        return state

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c29i",
            voice_source_ref="voice:c29i",
            registry_source_ref="registry:c29i",
            production_activation=False,
        )

    def wake(self, state):
        witness = build_runtime_liveness_witness(
            state=state,
            anchor=anchor("1", 111_000, 50_000, 8, EPOCH_A),
            source_ref="self-state-checkpoint-receipt:" + "c" * 64,
        )
        return wake_from_unplanned_restart(
            wake_anchor=anchor("2", 121_000, 200, 1, EPOCH_B),
            self_id=state.self_id,
            person_revision=state.person_revision,
            source_ref="sleep-wake-ack:" + "d" * 64,
            liveness_witness=witness,
        )

    def context(self, state, wake=None):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29i",
            wake_receipt=wake,
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c29i",
            provider="mock",
            model="c29i-model",
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

    def event(self, marker, sequence):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="operator_signal",
            source_ref="operator:c29i:" + marker,
            summary="C29-I explicit cognition event.",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def session(self, state, wake=None):
        engine = CaptureEngine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state, wake),
            durable_anchor_state=state,
        )
        return session, engine

    def test_window_open_and_consume_are_strict(self):
        state = self.durable()
        context = self.context(state, self.wake(state))
        window = open_continuity_reorientation_window(
            context.continuity_state
        )
        self.assertEqual(window.state, "ACTIVE")
        self.assertEqual(window.remaining_successful_runs, 1)
        consumed = consume_continuity_reorientation_window(
            window,
            cycle_id="cycle-" + "9" * 32,
        )
        self.assertEqual(consumed.state, "CONSUMED")
        self.assertEqual(consumed.remaining_successful_runs, 0)
        with self.assertRaises(ContinuityHorizonError):
            consume_continuity_reorientation_window(
                consumed,
                cycle_id="cycle-" + "8" * 32,
            )

    def test_idle_does_not_consume_window(self):
        state = self.durable()
        session, engine = self.session(state, self.wake(state))

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "IDLE")
        self.assertEqual(engine.calls, 0)
        self.assertEqual(
            session.continuity_reorientation_window.state,
            "ACTIVE",
        )

    def test_first_run_gets_continuity_second_run_does_not(self):
        state = self.durable()
        session, engine = self.session(state, self.wake(state))

        session.submit(self.event("7", 1))
        first = run(session.step(profile=self.profile()))

        self.assertEqual(first.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertIn("continuity", engine.contexts[0])
        self.assertEqual(
            engine.contexts[0]["continuity"]["knowledge"],
            "UNPLANNED_BOUNDED",
        )
        window = session.continuity_reorientation_window
        self.assertEqual(window.state, "CONSUMED")
        self.assertEqual(
            window.consumed_cycle_id,
            first.supervisor_step.cycle_result.cognitive_cycle.request.cycle_id,
        )
        self.assertIsNotNone(session.continuity_state)

        session.submit(self.event("8", 2))
        second = run(session.step(profile=self.profile()))

        self.assertEqual(second.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 2)
        self.assertNotIn("continuity", engine.contexts[1])
        self.assertEqual(
            session.continuity_reorientation_window.state,
            "CONSUMED",
        )
        self.assertIsNotNone(session.continuity_state)

    def test_no_wake_means_no_window(self):
        state = self.durable()
        session, engine = self.session(state)
        self.assertIsNone(session.continuity_state)
        self.assertIsNone(session.continuity_reorientation_window)
        self.assertEqual(engine.calls, 0)

    def test_close_clears_window_and_continuity(self):
        state = self.durable()
        session, _engine = self.session(state, self.wake(state))
        self.assertIsNotNone(session.continuity_reorientation_window)
        session.close()
        self.assertIsNone(session.continuity_reorientation_window)
        self.assertIsNone(session.continuity_state)


if __name__ == "__main__":
    unittest.main()
