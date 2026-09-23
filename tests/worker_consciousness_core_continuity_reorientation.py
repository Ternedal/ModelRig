#!/usr/bin/env python3
"""C29-G continuity reorientation policy tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ContinuityReorientationPolicy,
    PostWakeContinuityState,
    evaluate_continuity_reorientation,
)


class ContinuityReorientationTests(unittest.TestCase):
    def state(self, knowledge):
        common = dict(
            schema=(
                "kaliv-consciousness-core/"
                "post-wake-continuity-state/v1"
            ),
            self_id="self-" + "a" * 32,
            person_revision="person-r0007",
            wake_receipt_ref="wake-receipt:" + "b" * 64,
            continuity_preserved=True,
            cognition_during_gap=False,
            crash_timestamp_claimed=False,
            self_state_store_write_applied=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        shapes = {
            "PLANNED_EXACT": dict(
                continuity_id="continuity-" + "1" * 32,
                dormancy_kind="PLANNED_SLEEP",
                knowledge="PLANNED_EXACT",
                exact_offline_duration_ms=60_000,
                offline_duration_upper_bound_ms=None,
                duration_confidence=1.0,
                last_known_alive_witness_ref=None,
                last_known_alive_anchor_ref=None,
            ),
            "PLANNED_UNKNOWN": dict(
                continuity_id="continuity-" + "2" * 32,
                dormancy_kind="PLANNED_SLEEP",
                knowledge="PLANNED_UNKNOWN",
                exact_offline_duration_ms=None,
                offline_duration_upper_bound_ms=None,
                duration_confidence=0.0,
                last_known_alive_witness_ref=None,
                last_known_alive_anchor_ref=None,
            ),
            "UNPLANNED_BOUNDED": dict(
                continuity_id="continuity-" + "3" * 32,
                dormancy_kind="UNPLANNED_DORMANCY",
                knowledge="UNPLANNED_BOUNDED",
                exact_offline_duration_ms=None,
                offline_duration_upper_bound_ms=10_000,
                duration_confidence=1.0,
                last_known_alive_witness_ref=(
                    "runtime-liveness-witness:" + "c" * 64
                ),
                last_known_alive_anchor_ref=(
                    "temporal-anchor:anchor-" + "d" * 32
                ),
            ),
            "UNPLANNED_UNBOUNDED": dict(
                continuity_id="continuity-" + "4" * 32,
                dormancy_kind="UNPLANNED_DORMANCY",
                knowledge="UNPLANNED_UNBOUNDED",
                exact_offline_duration_ms=None,
                offline_duration_upper_bound_ms=None,
                duration_confidence=0.0,
                last_known_alive_witness_ref=None,
                last_known_alive_anchor_ref=None,
            ),
        }
        return PostWakeContinuityState(
            **common,
            **shapes[knowledge],
        )

    def test_default_policy_orders_all_four_states(self):
        expected = [
            (
                "PLANNED_EXACT",
                "ORDINARY",
                0.90,
                "planned_exact_duration",
            ),
            (
                "PLANNED_UNKNOWN",
                "UNCERTAINTY_ELEVATED",
                0.95,
                "planned_duration_uncertain",
            ),
            (
                "UNPLANNED_BOUNDED",
                "RECOVERY_ELEVATED",
                0.98,
                "unplanned_gap_bounded",
            ),
            (
                "UNPLANNED_UNBOUNDED",
                "RECOVERY_MAXIMUM",
                1.0,
                "unplanned_gap_unbounded",
            ),
        ]

        for knowledge, mode, salience, reason in expected:
            with self.subTest(knowledge=knowledge):
                decision = evaluate_continuity_reorientation(
                    self.state(knowledge)
                )
                self.assertEqual(decision.knowledge, knowledge)
                self.assertEqual(decision.mode, mode)
                self.assertEqual(
                    decision.attention_salience,
                    salience,
                )
                self.assertEqual(decision.reason, reason)
                self.assertEqual(decision.model_calls, 0)
                self.assertFalse(
                    decision.automatic_cognition_authority
                )
                self.assertFalse(decision.execution_authority)
                self.assertFalse(decision.scheduling_authority)
                self.assertFalse(
                    decision.durable_memory_write_authority
                )
                self.assertFalse(
                    decision.self_state_store_write_applied
                )

    def test_mapping_input_is_accepted_without_side_effects(self):
        state = self.state("UNPLANNED_BOUNDED")
        decision = evaluate_continuity_reorientation(
            state.model_dump(mode="python")
        )
        self.assertEqual(
            decision.mode,
            "RECOVERY_ELEVATED",
        )
        self.assertEqual(
            decision.attention_salience,
            0.98,
        )

    def test_custom_monotonic_policy_is_respected(self):
        policy = ContinuityReorientationPolicy(
            schema=(
                "kaliv-consciousness-core/"
                "continuity-reorientation-policy/v1"
            ),
            planned_exact_salience=0.5,
            planned_unknown_salience=0.6,
            unplanned_bounded_salience=0.7,
            unplanned_unbounded_salience=0.8,
            production_activation=False,
        )
        decision = evaluate_continuity_reorientation(
            self.state("UNPLANNED_UNBOUNDED"),
            policy=policy,
        )
        self.assertEqual(decision.attention_salience, 0.8)

    def test_non_monotonic_policy_fails_closed(self):
        with self.assertRaises(ValueError):
            ContinuityReorientationPolicy(
                schema=(
                    "kaliv-consciousness-core/"
                    "continuity-reorientation-policy/v1"
                ),
                planned_exact_salience=0.9,
                planned_unknown_salience=0.8,
                unplanned_bounded_salience=0.98,
                unplanned_unbounded_salience=1.0,
                production_activation=False,
            )


if __name__ == "__main__":
    unittest.main()
