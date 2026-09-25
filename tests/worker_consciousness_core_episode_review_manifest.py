#!/usr/bin/env python3
"""C30-U episode-review capability manifest qualification tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
    CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
    EPISODE_REVIEW_RUNTIME_FLAG,
    MAX_OBSERVABILITY_COUNTER,
    build_episode_review_capability_manifest,
)
from app.consciousness_core.episode_review_api import (  # noqa: E402
    build_consciousness_episode_review_router,
)


class EpisodeReviewCapabilityManifestTests(unittest.TestCase):
    def test_manifest_declares_exact_gates_routes_and_bounds(self):
        manifest = build_episode_review_capability_manifest()

        self.assertEqual(
            manifest.capability,
            "C30_EXPERIENTIAL_EPISODE_REVIEW",
        )
        self.assertEqual(manifest.slice_start, "C30-H")
        self.assertEqual(manifest.slice_end, "C30-T")
        self.assertEqual(
            manifest.runtime_flag,
            EPISODE_REVIEW_RUNTIME_FLAG,
        )
        self.assertEqual(
            manifest.transport_flag,
            CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
        )
        self.assertFalse(manifest.runtime_default_enabled)
        self.assertFalse(manifest.transport_default_enabled)
        self.assertTrue(manifest.transport_loopback_only)
        self.assertEqual(manifest.mailbox_default_capacity, 8)
        self.assertEqual(manifest.mailbox_max_capacity, 32)
        self.assertEqual(manifest.pending_list_max_items, 32)
        self.assertEqual(manifest.active_claim_max_count, 32)
        self.assertEqual(
            manifest.observability_counter_max,
            MAX_OBSERVABILITY_COUNTER,
        )
        self.assertEqual(
            manifest.operator_read_routes,
            [
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/manifest",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/status",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/attention",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/summary",
            ],
        )
        self.assertEqual(
            manifest.review_workflow_routes,
            [
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/pending",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/abandon",
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/commit",
            ],
        )

    def test_manifest_preserves_authority_denials(self):
        manifest = build_episode_review_capability_manifest()

        self.assertTrue(
            manifest.episode_boundary_review_publication_non_blocking
        )
        self.assertTrue(manifest.claim_keeps_request_pending)
        self.assertTrue(manifest.semantic_preflight_before_consume)
        self.assertTrue(manifest.exact_request_ref_binding)
        self.assertFalse(manifest.synthetic_cycle_allowed)
        self.assertFalse(
            manifest.synthetic_user_fact_reconstruction_allowed
        )
        self.assertFalse(
            manifest.episode_derived_completed_turn_authority
        )
        self.assertFalse(manifest.direct_memory4_write_authority)
        self.assertFalse(manifest.durable_review_store)
        self.assertFalse(manifest.durable_claim_recovery)
        self.assertFalse(manifest.automatic_semantic_review)
        self.assertFalse(manifest.raw_user_text_in_operator_status)
        self.assertFalse(manifest.raw_chain_of_thought_included)
        self.assertFalse(manifest.notifications_automatic)
        self.assertFalse(manifest.timers_authority)
        self.assertFalse(manifest.scheduling_authority)
        self.assertFalse(manifest.background_worker_authority)
        self.assertFalse(manifest.execution_authority)
        self.assertEqual(
            manifest.model_calls_from_review_control_plane,
            0,
        )
        self.assertFalse(manifest.production_activation)

    def test_manifest_is_static_and_does_not_echo_runtime_environment(self):
        old_runtime = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        old_transport = os.environ.get(
            CONSCIOUSNESS_EPISODE_REVIEW_FLAG
        )
        try:
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"

            manifest = build_episode_review_capability_manifest()

            self.assertFalse(manifest.runtime_default_enabled)
            self.assertFalse(manifest.transport_default_enabled)
            payload = manifest.model_dump_json()
            self.assertNotIn("ereq-", payload)
            self.assertNotIn("eclaim-", payload)
            self.assertNotIn("self-", payload)
            self.assertNotIn("person-r", payload)
            self.assertNotIn("pending_count", payload)
            self.assertNotIn("claimed_count", payload)
        finally:
            if old_runtime is None:
                os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            else:
                os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = old_runtime
            if old_transport is None:
                os.environ.pop(
                    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
                    None,
                )
            else:
                os.environ[
                    CONSCIOUSNESS_EPISODE_REVIEW_FLAG
                ] = old_transport

    def test_private_manifest_route_is_loopback_only_and_service_free(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_episode_review_router(
                loopback_allowed=lambda _request: True,
            )
        )
        response = TestClient(app).get(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/manifest"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["capability"],
            "C30_EXPERIENTIAL_EPISODE_REVIEW",
        )
        self.assertFalse(response.json()["production_activation"])

        denied = FastAPI()
        denied.include_router(
            build_consciousness_episode_review_router(
                loopback_allowed=lambda _request: False,
            )
        )
        rejected = TestClient(denied).get(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/manifest"
        )
        self.assertEqual(rejected.status_code, 403)

    def test_manifest_source_has_no_runtime_or_persistence_side_effects(self):
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "episode_review_manifest.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "create_task(",
            "threading",
            "asyncio",
            "sqlite3",
            "MemoryStore",
            "Memory4ExperienceBridge",
            "schedule_service",
            "submit_completed_turn",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
