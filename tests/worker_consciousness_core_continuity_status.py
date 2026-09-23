#!/usr/bin/env python3
"""C29-L read-only continuity status snapshot tests."""
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
        source_ref="trusted:c29l:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29l:" + marker,
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
        payload["interpretation"] = "C29-L status snapshot."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class ContinuityStatusTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29l",
            source_refs=["registry:test:c29l"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29l",
            world_state_ref="world-state:c29l",
            workspace_ref="workspace:c29l",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29l"],
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
            body_source_ref="body:c29l",
            voice_source_ref="voice:c29l",
            registry_source_ref="registry:c29l",
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
            bootstrap_source_ref="runtime:c29l",
            wake_receipt=wake,
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c29l",
            provider="mock",
            model="c29l-model",
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
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state, wake),
            durable_anchor_state=state,
        )
        return session, engine

    def event(self):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "7" * 32,
            kind="operator_signal",
            source_ref="operator:c29l",
            summary="C29-L explicit cognition event.",
            salience=1.0,
            observed_sequence=1,
            production_activation=False,
        )

    def test_no_wake_is_none_status(self):
        state = self.durable()
        session, engine = self.session(state)

        status = session.continuity_status

        self.assertEqual(status.status, "NONE")
        self.assertIsNone(status.knowledge)
        self.assertIsNone(status.continuity_state_ref)
        self.assertIsNone(status.orientation_state_ref)
        self.assertIsNone(status.recovery_completion_ref)
        self.assertFalse(status.direct_model_context_active)
        self.assertFalse(status.reorientation_complete)
        self.assertEqual(engine.calls, 0)

    def test_wake_starts_reorienting(self):
        state = self.durable()
        session, _engine = self.session(state, self.wake(state))

        status = session.continuity_status

        self.assertEqual(status.status, "REORIENTING")
        self.assertEqual(status.knowledge, "UNPLANNED_BOUNDED")
        self.assertTrue(status.direct_model_context_active)
        self.assertFalse(status.reorientation_complete)
        self.assertIsNotNone(status.continuity_state_ref)
        self.assertIsNotNone(status.orientation_state_ref)
        self.assertIsNone(status.recovery_completion_ref)

    def test_first_run_becomes_oriented(self):
        state = self.durable()
        session, engine = self.session(state, self.wake(state))
        session.submit(self.event())

        result = run(session.step(profile=self.profile()))
        status = session.continuity_status

        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertEqual(status.status, "ORIENTED")
        self.assertEqual(status.knowledge, "UNPLANNED_BOUNDED")
        self.assertFalse(status.direct_model_context_active)
        self.assertTrue(status.reorientation_complete)
        self.assertIsNotNone(status.recovery_completion_ref)

    def test_snapshot_does_not_expose_raw_lifecycle_fields(self):
        state = self.durable()
        session, _engine = self.session(state, self.wake(state))
        payload = session.continuity_status.model_dump(mode="json")

        forbidden = {
            "wake_receipt_ref",
            "last_known_alive_witness_ref",
            "last_known_alive_anchor_ref",
            "offline_duration_upper_bound_ms",
            "exact_offline_duration_ms",
            "sleep_id",
            "entry_anchor_ref",
        }
        self.assertTrue(forbidden.isdisjoint(payload.keys()))
        self.assertFalse(payload["persistence_authority"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["scheduling_authority"])
        self.assertFalse(payload["timer_authority"])


if __name__ == "__main__":
    unittest.main()
