#!/usr/bin/env python3
"""C29-K explicit recovery orientation phase tests."""
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
    ContinuityOrientationError,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_continuity_recovery_completion,
    build_runtime_liveness_witness,
    complete_continuity_orientation,
    consume_continuity_reorientation_window,
    continuity_orientation_state_ref,
    open_continuity_orientation,
    open_continuity_reorientation_window,
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
        source_ref="trusted:c29k:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29k:" + marker,
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


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "C29-K orientation phase."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class ContinuityOrientationTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29k",
            source_refs=["registry:test:c29k"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29k",
            world_state_ref="world-state:c29k",
            workspace_ref="workspace:c29k",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29k"],
            ),
        )

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c29k",
            voice_source_ref="voice:c29k",
            registry_source_ref="registry:c29k",
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

    def context(self, state):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29k",
            wake_receipt=self.wake(state),
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c29k",
            provider="mock",
            model="c29k-model",
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

    def event(self):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "7" * 32,
            kind="operator_signal",
            source_ref="operator:c29k",
            summary="C29-K explicit cognition event.",
            salience=1.0,
            observed_sequence=1,
            production_activation=False,
        )

    def session(self, state):
        engine = Engine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state),
            durable_anchor_state=state,
        )
        return session, engine

    def test_primitive_transitions_only_from_matching_active_state(self):
        state = self.durable()
        context = self.context(state)
        continuity = context.continuity_state
        active_window = open_continuity_reorientation_window(
            continuity
        )
        orientation = open_continuity_orientation(
            continuity_state=continuity,
            window=active_window,
        )

        self.assertEqual(orientation.phase, "REORIENTING")
        self.assertTrue(orientation.direct_model_context_active)
        self.assertFalse(orientation.reorientation_complete)

        consumed = consume_continuity_reorientation_window(
            active_window,
            cycle_id="cycle-" + "9" * 32,
        )
        completion = build_continuity_recovery_completion(
            continuity_state=continuity,
            consumed_window=consumed,
            transition_receipt_ref="transition:test",
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )
        oriented = complete_continuity_orientation(
            previous=orientation,
            continuity_state=continuity,
            window=consumed,
            completion=completion,
        )

        self.assertEqual(oriented.phase, "ORIENTED")
        self.assertFalse(oriented.direct_model_context_active)
        self.assertTrue(oriented.reorientation_complete)
        self.assertEqual(
            oriented.completed_cycle_id,
            "cycle-" + "9" * 32,
        )
        self.assertIsNotNone(oriented.recovery_completion_ref)
        self.assertTrue(
            continuity_orientation_state_ref(oriented).startswith(
                "continuity-orientation-state:"
            )
        )

        with self.assertRaises(ContinuityOrientationError):
            complete_continuity_orientation(
                previous=oriented,
                continuity_state=continuity,
                window=consumed,
                completion=completion,
            )

    def test_session_starts_reorienting(self):
        state = self.durable()
        session, engine = self.session(state)

        orientation = session.continuity_orientation
        self.assertEqual(orientation.phase, "REORIENTING")
        self.assertTrue(orientation.direct_model_context_active)
        self.assertIsNone(session.recovery_completion)
        self.assertEqual(engine.calls, 0)

    def test_idle_preserves_reorienting_phase(self):
        state = self.durable()
        session, engine = self.session(state)

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "IDLE")
        self.assertEqual(engine.calls, 0)
        self.assertEqual(
            session.continuity_orientation.phase,
            "REORIENTING",
        )
        self.assertIsNone(session.recovery_completion)

    def test_first_run_atomically_becomes_oriented(self):
        state = self.durable()
        session, engine = self.session(state)
        session.submit(self.event())

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        orientation = session.continuity_orientation
        completion = session.recovery_completion
        self.assertEqual(orientation.phase, "ORIENTED")
        self.assertFalse(orientation.direct_model_context_active)
        self.assertTrue(orientation.reorientation_complete)
        self.assertEqual(
            orientation.completed_cycle_id,
            completion.accepted_cycle_id,
        )
        self.assertEqual(
            orientation.completed_cycle_id,
            result.supervisor_step.cycle_result.cognitive_cycle.request.cycle_id,
        )
        self.assertIsNotNone(orientation.recovery_completion_ref)

    def test_close_clears_orientation(self):
        state = self.durable()
        session, _engine = self.session(state)
        self.assertIsNotNone(session.continuity_orientation)
        session.close()
        self.assertIsNone(session.continuity_orientation)


if __name__ == "__main__":
    unittest.main()
