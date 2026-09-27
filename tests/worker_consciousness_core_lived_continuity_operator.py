#!/usr/bin/env python3
"""C31-H privacy-safe operator status and capability-manifest tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CONTINUOUS_LOOP_FLAG,
    LivedContinuityInputs,
    build_lived_continuity_capability_manifest,
    build_lived_continuity_operator_status,
    build_lived_continuity_receipt,
    plan_continuous_loop_step,
)


class LivedContinuityOperatorStatusTests(unittest.TestCase):
    def continuity(self):
        return build_lived_continuity_receipt(
            LivedContinuityInputs(
                schema="kaliv-consciousness-core/lived-continuity-inputs/v1",
                self_id="self-" + "1" * 32,
                person_revision="person-r0007",
                cycle_id="cycle-" + "2" * 32,
                self_state_ref="self-state:test",
                temporal_state_ref="temporal:test",
                workspace_ref="workspace:test",
                thought_proposal_ref="proposal:test",
                production_activation=False,
            )
        )

    def test_empty_status_is_private_and_inert(self):
        status = build_lived_continuity_operator_status()
        self.assertEqual(status.state, "NO_EVIDENCE")
        self.assertFalse(status.continuity_present)
        self.assertFalse(status.loop_enabled)
        self.assertIsNone(status.loop_disposition)
        self.assertEqual(status.model_calls, 0)

        payload = status.model_dump(mode="json")
        self.assertNotIn("self_id", payload)
        self.assertNotIn("person_revision", payload)
        self.assertNotIn("continuity_loop_id", payload)
        self.assertNotIn("workspace_ref", payload)
        self.assertNotIn("thought_proposal_ref", payload)
        self.assertFalse(payload["raw_user_text_included"])
        self.assertFalse(payload["raw_assistant_text_included"])
        self.assertFalse(payload["raw_chain_of_thought_included"])
        self.assertFalse(payload["identity_refs_included"])
        self.assertFalse(payload["memory_refs_included"])

    def test_continuity_presence_does_not_echo_refs(self):
        status = build_lived_continuity_operator_status(
            continuity=self.continuity()
        )
        self.assertEqual(status.state, "CONTINUITY_PRESENT")
        self.assertTrue(status.continuity_present)
        encoded = status.model_dump_json()
        self.assertNotIn("self-", encoded)
        self.assertNotIn("person-r", encoded)
        self.assertNotIn("workspace:test", encoded)
        self.assertNotIn("proposal:test", encoded)

    def test_loop_plan_reports_bounded_disposition_only(self):
        plan = plan_continuous_loop_step(
            scheduler_tick_ref=None,
            supervisor_plan=None,
            env={},
        )
        status = build_lived_continuity_operator_status(loop_plan=plan)
        self.assertEqual(status.state, "LOOP_STEP_PLANNED")
        self.assertFalse(status.loop_enabled)
        self.assertEqual(status.loop_disposition, "DISABLED")
        self.assertFalse(status.execution_authority)
        self.assertFalse(status.scheduling_authority)
        self.assertFalse(status.timer_authority)

    def test_manifest_closes_exact_c31_chain_and_preserves_authorities(self):
        manifest = build_lived_continuity_capability_manifest()
        self.assertEqual(manifest.slice_start, "C31-A")
        self.assertEqual(manifest.slice_end, "C31-H")
        self.assertEqual(
            manifest.implemented_slices,
            [
                "C31-A", "C31-B", "C31-C", "C31-D",
                "C31-E", "C31-F", "C31-G", "C31-H",
            ],
        )
        self.assertEqual(manifest.continuous_loop_flag, CONTINUOUS_LOOP_FLAG)
        self.assertFalse(manifest.continuous_loop_default_enabled)
        self.assertTrue(manifest.thought_engine_replaceable)
        self.assertTrue(
            manifest.self_state_identity_preserved_across_model_swap
        )
        self.assertTrue(manifest.person_binding_preserved_across_model_swap)
        self.assertTrue(
            manifest.durable_memory_binding_preserved_across_model_swap
        )
        self.assertTrue(manifest.powered_off_time_is_dormancy)
        self.assertFalse(manifest.cognition_during_gap_allowed)
        self.assertTrue(manifest.explicit_wake_reorientation_required)
        self.assertFalse(manifest.automatic_durable_memory_write)
        self.assertFalse(manifest.continuous_loop_internal_repeat)
        self.assertFalse(manifest.continuous_loop_internal_timer)
        self.assertEqual(manifest.max_cycles_per_supervisor_plan, 1)
        self.assertTrue(manifest.agent3_execution_required)
        self.assertTrue(manifest.existing_runtime_gates_required)
        self.assertFalse(manifest.identity_authority)
        self.assertFalse(manifest.persistent_state_authority)
        self.assertFalse(manifest.durable_memory_write_authority)
        self.assertFalse(manifest.execution_authority)
        self.assertFalse(manifest.scheduling_authority)
        self.assertFalse(manifest.model_authority)
        self.assertFalse(manifest.production_activation)

    def test_manifest_is_static_and_contains_no_live_refs(self):
        encoded = build_lived_continuity_capability_manifest().model_dump_json()
        for forbidden in (
            "self-",
            "person-r",
            "cycle-",
            "workspace:",
            "memory4:",
            "cognitive-profile:",
        ):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
