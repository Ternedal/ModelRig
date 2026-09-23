#!/usr/bin/env python3
"""C29-F bounded continuity context projection tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_continuity_context.py
"""
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
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_post_wake_continuity_state,
    build_runtime_liveness_witness,
    prepare_sleep,
    wake_from_sleep,
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
EPOCH_C = "epoch-" + "3" * 32


def run(coro):
    return asyncio.run(coro)


def sample(marker: str, wall: int, mono: int, seq: int, epoch: str):
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
        source_ref="trusted:c29f:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker: str, wall: int, mono: int, seq: int, epoch: str):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29f:" + marker,
    )


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 64)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 64))
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
        payload["interpretation"] = "C29-F continuity projection."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class ContinuityContextTests(unittest.TestCase):
    def durable(self, *, self_id=SELF, person_id=PERSON):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=self_id,
            person_id=person_id,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29f",
            source_refs=["registry:test:c29f"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29f",
            world_state_ref="world-state:c29f",
            workspace_ref="workspace:c29f",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29f"],
            ),
        )
        return authority, state

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c29f",
            voice_source_ref="voice:c29f",
            registry_source_ref="registry:c29f",
            production_activation=False,
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c29f",
            provider="mock",
            model="c29f-model",
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

    def planned_wake(self, state):
        sleep = prepare_sleep(
            self_id=state.self_id,
            person_revision=state.person_revision,
            entry_anchor=anchor("1", 1_000, 9_000, 1, EPOCH_A),
            reason="app_closed",
        )
        return wake_from_sleep(
            wake_anchor=anchor("2", 61_000, 100, 2, EPOCH_B),
            sleep_record=sleep,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

    def bounded_unplanned_wake(self, state):
        witness = build_runtime_liveness_witness(
            state=state,
            anchor=anchor("3", 111_000, 50_000, 8, EPOCH_B),
            source_ref="self-state-checkpoint-receipt:" + "c" * 64,
        )
        return wake_from_unplanned_restart(
            wake_anchor=anchor("4", 121_000, 200, 1, EPOCH_C),
            self_id=state.self_id,
            person_revision=state.person_revision,
            source_ref="sleep-wake-ack:" + "d" * 64,
            liveness_witness=witness,
        )

    def context(self, state, wake=None):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29f",
            wake_receipt=wake,
        )

    def test_no_continuity_keeps_pre_c29f_engine_context_shape(self):
        _authority, state = self.durable()
        context = self.context(state)
        engine = CaptureEngine()
        cycle = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(engine)
        )

        run(
            cycle.run(
                state=context.state,
                world=context.world,
                workspace=context.workspace,
                personality_snapshot=context.personality_snapshot,
                profile=self.profile(),
            )
        )

        self.assertEqual(engine.calls, 1)
        self.assertNotIn("continuity", engine.contexts[0])

    def test_unplanned_bound_is_projected_without_liveness_internals(self):
        _authority, state = self.durable()
        wake = self.bounded_unplanned_wake(state)
        context = self.context(state, wake)
        engine = CaptureEngine()
        cycle = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(engine)
        )

        run(
            cycle.run(
                state=context.state,
                world=context.world,
                workspace=context.workspace,
                personality_snapshot=context.personality_snapshot,
                profile=self.profile(),
                continuity_state=context.continuity_state,
            )
        )

        projection = engine.contexts[0]["continuity"]
        self.assertEqual(
            projection["knowledge"],
            "UNPLANNED_BOUNDED",
        )
        self.assertEqual(
            projection["offline_duration_upper_bound_ms"],
            10_000,
        )
        self.assertIsNone(
            projection["exact_offline_duration_ms"]
        )
        self.assertFalse(projection["cognition_during_gap"])
        self.assertFalse(projection["crash_timestamp_claimed"])
        self.assertFalse(projection["identity_authority"])
        self.assertFalse(projection["persistent_state_authority"])
        self.assertFalse(projection["execution_authority"])
        self.assertNotIn(
            "last_known_alive_witness_ref",
            projection,
        )
        self.assertNotIn(
            "last_known_alive_anchor_ref",
            projection,
        )
        self.assertNotIn("wake_receipt_ref", projection)

    def test_planned_exact_projection_contains_only_exact_duration(self):
        _authority, state = self.durable()
        wake = self.planned_wake(state)
        context = self.context(state, wake)
        engine = CaptureEngine()
        cycle = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(engine)
        )

        run(
            cycle.run(
                state=context.state,
                world=context.world,
                workspace=context.workspace,
                personality_snapshot=context.personality_snapshot,
                profile=self.profile(),
                continuity_state=context.continuity_state,
            )
        )

        projection = engine.contexts[0]["continuity"]
        self.assertEqual(projection["knowledge"], "PLANNED_EXACT")
        self.assertEqual(
            projection["exact_offline_duration_ms"],
            60_000,
        )
        self.assertIsNone(
            projection["offline_duration_upper_bound_ms"]
        )

    def test_foreign_continuity_is_rejected_before_model(self):
        _authority, state = self.durable()
        context = self.context(state)
        _foreign_authority, foreign = self.durable(
            self_id="self-" + "f" * 32,
            person_id="person-" + "e" * 32,
        )
        foreign_wake = self.planned_wake(foreign)
        foreign_continuity = build_post_wake_continuity_state(
            foreign_wake,
            expected_self_id=foreign.self_id,
            expected_person_revision=foreign.person_revision,
        )
        engine = CaptureEngine()
        cycle = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(engine)
        )

        with self.assertRaisesRegex(
            Exception,
            "continuity state belongs to another self",
        ):
            run(
                cycle.run(
                    state=context.state,
                    world=context.world,
                    workspace=context.workspace,
                    personality_snapshot=context.personality_snapshot,
                    profile=self.profile(),
                    continuity_state=foreign_continuity,
                )
            )

        self.assertEqual(engine.calls, 0)

    def test_production_session_threads_continuity_to_model(self):
        _authority, state = self.durable()
        wake = self.bounded_unplanned_wake(state)
        context = self.context(state, wake)
        engine = CaptureEngine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=context,
            durable_anchor_state=state,
        )
        event = CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "9" * 32,
            kind="wake_followup",
            source_ref="wake:test:c29f",
            summary="C29-F wake continuity context.",
            salience=1.0,
            observed_sequence=1,
            production_activation=False,
        )
        session.submit(event)

        result = run(session.step(profile=self.profile()))

        self.assertEqual(
            result.supervisor_step.plan.decision,
            "RUN",
        )
        self.assertEqual(engine.calls, 1)
        self.assertEqual(
            engine.contexts[0]["continuity"]["knowledge"],
            "UNPLANNED_BOUNDED",
        )
        self.assertEqual(
            engine.contexts[0]["continuity"][
                "offline_duration_upper_bound_ms"
            ],
            10_000,
        )


if __name__ == "__main__":
    unittest.main()
