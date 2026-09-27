#!/usr/bin/env python3
"""C31-H operator status and consolidated qualification tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (
    build_lived_continuity_capability_manifest,
    build_lived_continuity_operator_status,
)


class LivedContinuityQualificationTests(unittest.TestCase):
    def test_incomplete_status_is_bounded_and_privacy_safe(self):
        status = build_lived_continuity_operator_status(
            slice_a_present=True,
            slice_b_present=True,
            slice_c_present=True,
            slice_d_present=True,
            slice_e_present=True,
            slice_f_present=True,
            slice_g_present=False,
        )
        self.assertEqual(status.state, "INCOMPLETE")
        self.assertEqual(status.slices_present, 6)
        self.assertFalse(status.complete_stack)
        payload = status.model_dump_json()
        for forbidden in (
            "self-",
            "person-",
            "person-r",
            "memory4:",
            "episode:",
            "engine:",
            "thinkreq-",
        ):
            self.assertNotIn(forbidden, payload.lower())
        self.assertFalse(status.raw_text_included)
        self.assertFalse(status.raw_chain_of_thought_included)
        self.assertFalse(status.identity_ids_included)
        self.assertFalse(status.memory_refs_included)
        self.assertFalse(status.model_identity_included)
        self.assertEqual(status.model_calls, 0)
        self.assertEqual(status.persistent_writes, 0)
        self.assertFalse(status.production_activation)

    def test_complete_status_requires_all_prior_c31_slices(self):
        status = build_lived_continuity_operator_status(
            slice_a_present=True,
            slice_b_present=True,
            slice_c_present=True,
            slice_d_present=True,
            slice_e_present=True,
            slice_f_present=True,
            slice_g_present=True,
        )
        self.assertEqual(status.state, "QUALIFIED")
        self.assertEqual(status.slices_present, 7)
        self.assertTrue(status.complete_stack)

    def test_manifest_matches_c31_acceptance_contract(self):
        manifest = build_lived_continuity_capability_manifest()
        self.assertEqual(manifest.capability, "C31_LIVED_CONTINUITY_LOOP")
        self.assertEqual(manifest.slice_start, "C31-A")
        self.assertEqual(manifest.slice_end, "C31-H")
        self.assertTrue(manifest.thought_engine_external_replaceable)
        self.assertFalse(manifest.raw_chain_of_thought_persisted)
        self.assertFalse(manifest.raw_chain_of_thought_exposed)
        self.assertFalse(manifest.powered_off_cognition_fabricated)
        self.assertTrue(manifest.time_perception_evidence_backed)
        self.assertTrue(manifest.existing_sleep_wake_lifecycle_reused)
        self.assertTrue(manifest.c30_context_requires_explicit_refs)
        self.assertTrue(manifest.memory4_durable_memory_authority)
        self.assertTrue(manifest.agent3_execution_authority)
        self.assertTrue(manifest.person_profile_identity_authority)
        self.assertTrue(manifest.runtime_composition_independently_gated)
        self.assertFalse(manifest.runtime_composition_default_enabled)
        self.assertFalse(manifest.thought_engine_identity_authority)
        self.assertFalse(manifest.thought_engine_durable_memory_authority)
        self.assertFalse(manifest.thought_engine_execution_authority)
        self.assertFalse(manifest.thought_engine_scheduling_authority)
        self.assertFalse(manifest.production_activation)

    def test_manifest_and_status_sources_have_no_side_effect_primitives(self):
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "lived_continuity_status.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "create_task(",
            "threading",
            "asyncio",
            "sqlite3",
            "MemoryStore",
            "schedule_service",
            "requests.",
            "httpx.",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
