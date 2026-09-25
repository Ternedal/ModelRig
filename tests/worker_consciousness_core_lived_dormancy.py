#!/usr/bin/env python3
"""C31-D lived dormancy bridge contracts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    LivedDormancyBridgeError,
    LivedDormancyBridgeReceipt,
    anchor_from_clock,
    build_continuity_recovery_completion,
    build_lived_dormancy_bridge,
    build_post_wake_continuity_state,
    complete_continuity_orientation,
    consume_continuity_reorientation_window,
    evaluate_continuity_reorientation,
    open_continuity_orientation,
    open_continuity_reorientation_window,
    prepare_sleep,
    wake_from_sleep,
    wake_from_unplanned_restart,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32


def anchor(marker: str, wall: int, mono: int, seq: int, epoch: str):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + marker * 32,
        wall_time_unix_ms=wall,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=10,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c31d:" + marker,
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref="c31d:" + marker)


class LivedDormancyBridgeTests(unittest.TestCase):
    def planned(self):
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON_REV,
            entry_anchor=anchor("1", 1_000, 10_000, 1, EPOCH_A),
            reason="app_closed",
            durable_self_state_ref="self-state:planned",
            durable_self_state_revision=7,
            open_goal_refs=["goal:resume"],
            open_loop_refs=["loop:resume"],
            pending_review_refs=["review:resume"],
        )
        wake = wake_from_sleep(
            wake_anchor=anchor("2", 61_000, 100, 2, EPOCH_B),
            sleep_record=sleep,
            expected_self_id=SELF,
            expected_person_revision=PERSON_REV,
        )
        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=SELF,
            expected_person_revision=PERSON_REV,
        )
        decision = evaluate_continuity_reorientation(continuity)
        window = open_continuity_reorientation_window(continuity)
        orientation = open_continuity_orientation(
            continuity_state=continuity,
            window=window,
        )
        return sleep, wake, continuity, decision, window, orientation

    def unplanned(self):
        wake = wake_from_unplanned_restart(
            wake_anchor=anchor("3", 121_000, 200, 1, EPOCH_B),
            self_id=SELF,
            person_revision=PERSON_REV,
            source_ref="runtime-restart:c31d",
        )
        continuity = build_post_wake_continuity_state(
            wake,
            expected_self_id=SELF,
            expected_person_revision=PERSON_REV,
        )
        decision = evaluate_continuity_reorientation(continuity)
        window = open_continuity_reorientation_window(continuity)
        orientation = open_continuity_orientation(
            continuity_state=continuity,
            window=window,
        )
        return wake, continuity, decision, window, orientation

    def test_planned_gap_is_explicit_reference_only_reorientation(self):
        sleep, wake, continuity, decision, window, orientation = self.planned()

        first = build_lived_dormancy_bridge(
            sleep_record=sleep,
            wake_receipt=wake,
            continuity_state=continuity,
            reorientation_decision=decision,
            reorientation_window=window,
            orientation_state=orientation,
        )
        second = build_lived_dormancy_bridge(
            sleep_record=sleep,
            wake_receipt=wake,
            continuity_state=continuity,
            reorientation_decision=decision,
            reorientation_window=window,
            orientation_state=orientation,
        )

        self.assertIsInstance(first, LivedDormancyBridgeReceipt)
        self.assertEqual(first, second)
        self.assertEqual(first.dormancy_kind, "PLANNED_SLEEP")
        self.assertEqual(first.knowledge, "PLANNED_EXACT")
        self.assertIsNotNone(first.sleep_record_ref)
        self.assertEqual(first.reorientation_phase, "REORIENTING")
        self.assertTrue(first.explicit_reorientation_required)
        self.assertFalse(first.reorientation_complete)
        self.assertTrue(first.continuity_preserved)
        self.assertFalse(first.cognition_during_gap)
        self.assertFalse(first.hidden_cognition_claimed)
        self.assertFalse(first.crash_timestamp_claimed)
        self.assertEqual(first.model_calls, 0)
        self.assertFalse(first.persistent_state_authority)
        self.assertFalse(first.self_state_store_write_applied)
        self.assertFalse(first.durable_memory_write_authority)
        self.assertFalse(first.automatic_cognition_authority)
        self.assertFalse(first.execution_authority)
        self.assertFalse(first.scheduling_authority)
        self.assertFalse(first.timer_authority)
        self.assertFalse(first.production_activation)

    def test_unplanned_gap_cannot_invent_sleep_or_crash_time(self):
        wake, continuity, decision, window, orientation = self.unplanned()
        receipt = build_lived_dormancy_bridge(
            wake_receipt=wake,
            continuity_state=continuity,
            reorientation_decision=decision,
            reorientation_window=window,
            orientation_state=orientation,
        )

        self.assertEqual(receipt.dormancy_kind, "UNPLANNED_DORMANCY")
        self.assertEqual(receipt.knowledge, "UNPLANNED_UNBOUNDED")
        self.assertIsNone(receipt.sleep_record_ref)
        self.assertFalse(receipt.cognition_during_gap)
        self.assertFalse(receipt.hidden_cognition_claimed)
        self.assertFalse(receipt.crash_timestamp_claimed)
        self.assertEqual(receipt.reorientation_phase, "REORIENTING")
        self.assertFalse(receipt.reorientation_complete)

    def test_planned_and_unplanned_sleep_binding_fail_closed(self):
        sleep, wake, continuity, decision, window, orientation = self.planned()

        with self.assertRaisesRegex(
            LivedDormancyBridgeError,
            "requires the exact SleepRecord",
        ):
            build_lived_dormancy_bridge(
                wake_receipt=wake,
                continuity_state=continuity,
                reorientation_decision=decision,
                reorientation_window=window,
                orientation_state=orientation,
            )

        (
            unplanned_wake,
            unplanned_continuity,
            unplanned_decision,
            unplanned_window,
            unplanned_orientation,
        ) = self.unplanned()
        with self.assertRaisesRegex(
            LivedDormancyBridgeError,
            "cannot carry a SleepRecord",
        ):
            build_lived_dormancy_bridge(
                sleep_record=sleep,
                wake_receipt=unplanned_wake,
                continuity_state=unplanned_continuity,
                reorientation_decision=unplanned_decision,
                reorientation_window=unplanned_window,
                orientation_state=unplanned_orientation,
            )

    def test_cross_continuity_reorientation_fails_closed(self):
        sleep, wake, continuity, decision, window, orientation = self.planned()
        foreign = decision.model_copy(
            update={
                "continuity_state_ref":
                    "post-wake-continuity-state:" + "f" * 64
            }
        )

        with self.assertRaisesRegex(
            LivedDormancyBridgeError,
            "decision belongs to another continuity state",
        ):
            build_lived_dormancy_bridge(
                sleep_record=sleep,
                wake_receipt=wake,
                continuity_state=continuity,
                reorientation_decision=foreign,
                reorientation_window=window,
                orientation_state=orientation,
            )

    def test_oriented_bridge_requires_exact_first_run_completion(self):
        sleep, wake, continuity, decision, active, reorienting = self.planned()
        consumed = consume_continuity_reorientation_window(
            active,
            cycle_id="cycle-" + "9" * 32,
        )
        completion = build_continuity_recovery_completion(
            continuity_state=continuity,
            consumed_window=consumed,
            transition_receipt_ref="transition:c31d:first-run",
            expected_self_id=SELF,
            expected_person_revision=PERSON_REV,
        )
        oriented = complete_continuity_orientation(
            previous=reorienting,
            continuity_state=continuity,
            window=consumed,
            completion=completion,
        )

        with self.assertRaisesRegex(
            LivedDormancyBridgeError,
            "requires recovery completion",
        ):
            build_lived_dormancy_bridge(
                sleep_record=sleep,
                wake_receipt=wake,
                continuity_state=continuity,
                reorientation_decision=decision,
                reorientation_window=consumed,
                orientation_state=oriented,
            )

        receipt = build_lived_dormancy_bridge(
            sleep_record=sleep,
            wake_receipt=wake,
            continuity_state=continuity,
            reorientation_decision=decision,
            reorientation_window=consumed,
            orientation_state=oriented,
            recovery_completion=completion,
        )
        self.assertEqual(receipt.reorientation_phase, "ORIENTED")
        self.assertTrue(receipt.reorientation_complete)
        self.assertIsNotNone(receipt.recovery_completion_ref)
        self.assertFalse(receipt.cognition_during_gap)
        self.assertFalse(receipt.hidden_cognition_claimed)


if __name__ == "__main__":
    unittest.main()
