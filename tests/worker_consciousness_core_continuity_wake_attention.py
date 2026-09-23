#!/usr/bin/env python3
"""C29-H continuity-aware wake attention tests."""
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
    SelfAffect,
    SelfBootstrapAuthority,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_post_wake_continuity_state,
    build_runtime_liveness_witness,
    build_wake_followup_event,
    prepare_sleep,
    wake_from_sleep,
    wake_from_unplanned_restart,
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
        source_ref="trusted:c29h:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker: str, wall: int, mono: int, seq: int, epoch: str):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29h:" + marker,
    )


class ContinuityWakeAttentionTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29h",
            source_refs=["registry:test:c29h"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29h",
            world_state_ref="world-state:c29h",
            workspace_ref="workspace:c29h",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29h"],
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
            body_source_ref="body:c29h",
            voice_source_ref="voice:c29h",
            registry_source_ref="registry:c29h",
            production_activation=False,
        )

    def planned(self, state, *, unknown=False):
        sleep = prepare_sleep(
            self_id=state.self_id,
            person_revision=state.person_revision,
            entry_anchor=anchor(
                "1",
                10_000 if unknown else 1_000,
                9_000,
                1,
                EPOCH_A,
            ),
            reason="app_closed",
        )
        return wake_from_sleep(
            wake_anchor=anchor(
                "2",
                9_000 if unknown else 61_000,
                100,
                2,
                EPOCH_B,
            ),
            sleep_record=sleep,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

    def unplanned(self, state, *, bounded):
        witness = None
        if bounded:
            witness = build_runtime_liveness_witness(
                state=state,
                anchor=anchor(
                    "3",
                    111_000,
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

    def cases(self, state):
        return [
            ("PLANNED_EXACT", self.planned(state), 0.90),
            (
                "PLANNED_UNKNOWN",
                self.planned(state, unknown=True),
                0.95,
            ),
            (
                "UNPLANNED_BOUNDED",
                self.unplanned(state, bounded=True),
                0.98,
            ),
            (
                "UNPLANNED_UNBOUNDED",
                self.unplanned(state, bounded=False),
                1.0,
            ),
        ]

    def test_direct_c26_without_continuity_keeps_legacy_salience(self):
        state = self.durable()
        wake = self.planned(state)
        event = build_wake_followup_event(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )
        self.assertEqual(event.salience, 0.96)

    def test_c26_uses_exact_c29g_salience_for_all_classes(self):
        state = self.durable()
        for knowledge, wake, expected in self.cases(state):
            with self.subTest(knowledge=knowledge):
                continuity = build_post_wake_continuity_state(
                    wake,
                    expected_self_id=state.self_id,
                    expected_person_revision=state.person_revision,
                )
                event = build_wake_followup_event(
                    wake,
                    expected_self_id=state.self_id,
                    expected_person_revision=state.person_revision,
                    continuity_state=continuity,
                )
                self.assertEqual(
                    continuity.knowledge,
                    knowledge,
                )
                self.assertEqual(event.salience, expected)
                self.assertEqual(event.kind, "wake_followup")

    def test_c19_workspace_uses_same_reorientation_salience(self):
        state = self.durable()
        for knowledge, wake, expected in self.cases(state):
            with self.subTest(knowledge=knowledge):
                context = bootstrap_runtime_session(
                    persistent_state=state,
                    active_person=self.person(state),
                    bootstrap_source_ref=(
                        "runtime:c29h:" + knowledge.lower()
                    ),
                    wake_receipt=wake,
                )
                self.assertEqual(
                    context.continuity_state.knowledge,
                    knowledge,
                )
                wake_candidates = [
                    item
                    for item in context.workspace.candidates
                    if "Wake reorientation after" in item.summary
                ]
                self.assertEqual(len(wake_candidates), 1)
                self.assertEqual(
                    wake_candidates[0].salience,
                    expected,
                )

    def test_c26_rejects_continuity_from_another_wake(self):
        state = self.durable()
        wake = self.planned(state)
        other = self.unplanned(state, bounded=False)
        continuity = build_post_wake_continuity_state(
            other,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        with self.assertRaisesRegex(
            Exception,
            "another WakeReceipt",
        ):
            build_wake_followup_event(
                wake,
                expected_self_id=state.self_id,
                expected_person_revision=state.person_revision,
                continuity_state=continuity,
            )


if __name__ == "__main__":
    unittest.main()
