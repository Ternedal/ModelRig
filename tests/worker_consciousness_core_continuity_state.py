#!/usr/bin/env python3
"""C29-E post-wake continuity state tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_continuity_state.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    ClockSample,
    ConsciousnessCoreRuntime,
    ContinuityStateError,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_post_wake_continuity_state,
    build_runtime_liveness_witness,
    post_wake_continuity_state_ref,
    prepare_sleep,
    wake_from_sleep,
    wake_from_unplanned_restart,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32
EPOCH_C = "epoch-" + "3" * 32


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
        source_ref="trusted:c29e:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker: str, wall: int, mono: int, seq: int, epoch: str):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29e:" + marker,
    )


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise AssertionError("C29-E must not call model")


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 32)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 32))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class ContinuityStateTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29e",
            source_refs=["registry:test:c29e"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29e",
            world_state_ref="world-state:c29e",
            workspace_ref="workspace:c29e",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29e"],
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
            body_source_ref="body:c29e",
            voice_source_ref="voice:c29e",
            registry_source_ref="registry:c29e",
            production_activation=False,
        )

    def planned(self, state, *, rollback=False):
        sleep = prepare_sleep(
            self_id=state.self_id,
            person_revision=state.person_revision,
            entry_anchor=anchor(
                "1",
                10_000 if rollback else 1_000,
                9_000,
                1,
                EPOCH_A,
            ),
            reason="app_closed",
        )
        return wake_from_sleep(
            wake_anchor=anchor(
                "2",
                9_000 if rollback else 61_000,
                100,
                2,
                EPOCH_B,
            ),
            sleep_record=sleep,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

    def unplanned(self, state, *, bounded=True, rollback=False):
        witness = None
        if bounded or rollback:
            witness = build_runtime_liveness_witness(
                state=state,
                anchor=anchor(
                    "3",
                    130_000 if rollback else 111_000,
                    50_000,
                    8,
                    EPOCH_B,
                ),
                source_ref=(
                    "self-state-checkpoint-receipt:" + "c" * 64
                ),
            )
        return wake_from_unplanned_restart(
            wake_anchor=anchor(
                "4",
                121_000,
                200,
                1,
                EPOCH_C,
            ),
            self_id=state.self_id,
            person_revision=state.person_revision,
            source_ref="sleep-wake-ack:" + "d" * 64,
            liveness_witness=witness,
        )

    def test_planned_exact_is_explicit_exact_knowledge(self):
        _authority, state = self.durable()
        wake = self.planned(state)

        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(continuity.knowledge, "PLANNED_EXACT")
        self.assertEqual(
            continuity.exact_offline_duration_ms,
            60_000,
        )
        self.assertIsNone(
            continuity.offline_duration_upper_bound_ms
        )
        self.assertIsNone(
            continuity.last_known_alive_witness_ref
        )
        self.assertFalse(continuity.crash_timestamp_claimed)
        self.assertFalse(continuity.cognition_during_gap)
        self.assertEqual(continuity.model_calls, 0)

    def test_planned_rollback_is_planned_unknown(self):
        _authority, state = self.durable()
        wake = self.planned(state, rollback=True)

        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(
            continuity.knowledge,
            "PLANNED_UNKNOWN",
        )
        self.assertIsNone(
            continuity.exact_offline_duration_ms
        )
        self.assertIsNone(
            continuity.offline_duration_upper_bound_ms
        )
        self.assertEqual(continuity.duration_confidence, 0.0)

    def test_unplanned_bounded_never_becomes_exact_duration(self):
        _authority, state = self.durable()
        wake = self.unplanned(state, bounded=True)

        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(
            continuity.knowledge,
            "UNPLANNED_BOUNDED",
        )
        self.assertIsNone(
            continuity.exact_offline_duration_ms
        )
        self.assertEqual(
            continuity.offline_duration_upper_bound_ms,
            10_000,
        )
        self.assertEqual(continuity.duration_confidence, 1.0)
        self.assertIsNotNone(
            continuity.last_known_alive_witness_ref
        )
        self.assertIsNotNone(
            continuity.last_known_alive_anchor_ref
        )
        self.assertFalse(continuity.crash_timestamp_claimed)

    def test_unplanned_without_numeric_bound_is_unbounded(self):
        _authority, state = self.durable()
        wake = self.unplanned(state, bounded=False)

        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(
            continuity.knowledge,
            "UNPLANNED_UNBOUNDED",
        )
        self.assertIsNone(
            continuity.exact_offline_duration_ms
        )
        self.assertIsNone(
            continuity.offline_duration_upper_bound_ms
        )
        self.assertIsNone(
            continuity.last_known_alive_witness_ref
        )
        self.assertEqual(continuity.duration_confidence, 0.0)

    def test_unplanned_clock_rollback_keeps_evidence_but_no_bound(self):
        _authority, state = self.durable()
        wake = self.unplanned(
            state,
            bounded=False,
            rollback=True,
        )

        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(
            continuity.knowledge,
            "UNPLANNED_UNBOUNDED",
        )
        self.assertIsNone(
            continuity.offline_duration_upper_bound_ms
        )
        self.assertIsNotNone(
            continuity.last_known_alive_witness_ref
        )
        self.assertIsNotNone(
            continuity.last_known_alive_anchor_ref
        )

    def test_foreign_identity_fails_closed(self):
        _authority, state = self.durable()
        wake = self.planned(state)

        with self.assertRaisesRegex(
            ContinuityStateError,
            "another self",
        ):
            build_post_wake_continuity_state(
                wake,
                expected_self_id="self-" + "f" * 32,
                expected_person_revision=state.person_revision,
            )

    def test_c19_bootstrap_retains_exact_continuity_state(self):
        _authority, state = self.durable()
        wake = self.unplanned(state, bounded=True)
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29e",
            wake_receipt=wake,
        )

        self.assertIsNotNone(context.continuity_state)
        continuity = context.continuity_state
        self.assertEqual(
            continuity.knowledge,
            "UNPLANNED_BOUNDED",
        )
        continuity_ref = post_wake_continuity_state_ref(
            continuity
        )
        wake_observation = [
            item
            for item in context.world.observations
            if item.subject_ref == f"self:{state.self_id}"
            and "UNPLANNED_DORMANCY" in item.proposition
        ][0]
        self.assertIn(
            continuity_ref,
            wake_observation.source_refs,
        )

    def test_live_session_exposes_then_clears_process_local_continuity(self):
        _authority, state = self.durable()
        wake = self.unplanned(state, bounded=True)
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29e:session",
            wake_receipt=wake,
        )
        engine = Engine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=context,
            durable_anchor_state=state,
        )

        self.assertIsNotNone(session.continuity_state)
        self.assertEqual(
            session.continuity_state.knowledge,
            "UNPLANNED_BOUNDED",
        )
        self.assertEqual(engine.calls, 0)

        session.close()

        self.assertIsNone(session.continuity_state)
        self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
