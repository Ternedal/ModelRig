from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.consciousness_core.status_api import (
    build_consciousness_status_router,
    runtime_instance_ref,
)
from app.consciousness_core.session_lifecycle import ProductionCognitiveSession


class ConsciousnessRuntimeStatusTests(unittest.TestCase):
    def test_status_is_privacy_safe_and_reports_disabled_baseline(self):
        app = FastAPI()
        app.include_router(build_consciousness_status_router())
        with patch.dict(os.environ, {}, clear=True):
            response = TestClient(app).get("/experimental/consciousness/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["schema"],
            "kaliv-consciousness-core/runtime-status/v1",
        )
        self.assertRegex(
            body["runtime_instance_ref"],
            r"^runtime-instance:[0-9a-f]{32}$",
        )
        self.assertEqual(body["runtime_instance_ref"], runtime_instance_ref())
        self.assertEqual(runtime_instance_ref(), runtime_instance_ref())
        self.assertFalse(body["enabled"]["core"])
        self.assertFalse(body["enabled"]["continuous_loop"])
        self.assertFalse(body["enabled"]["autonomous_cognition"])
        self.assertFalse(body["mounted"]["live_session"])
        self.assertFalse(body["mounted"]["autonomous_scheduler"])
        self.assertFalse(body["ready_for_user_driven_cognition"])
        self.assertFalse(body["ready_for_lived_continuity"])
        self.assertIsNone(body["autonomous_scheduler_status"])
        self.assertFalse(body["lived_continuity"]["temporal_state_present"])
        self.assertFalse(body["lived_continuity"]["receipt_present"])
        self.assertFalse(body["lived_continuity"]["present_context_present"])
        self.assertFalse(body["production_activation"])

        encoded = str(body).lower()
        for forbidden in (
            "self_id",
            "person_id",
            "event_id",
            "prompt",
            "chain_of_thought",
            "memory_ref",
            "process_id",
            "pid",
            "hostname",
        ):
            self.assertNotIn(forbidden, encoded)


    def test_evidence_snapshot_is_default_off(self):
        app = FastAPI()
        app.include_router(build_consciousness_status_router())
        with patch.dict(os.environ, {}, clear=True):
            response = TestClient(app).get(
                "/experimental/consciousness/evidence-snapshot"
            )
        self.assertEqual(response.status_code, 404)

    def test_evidence_snapshot_is_read_only_when_explicitly_enabled(self):
        class Dumpable:
            def __init__(self, payload):
                self.payload = payload

            def model_dump(self, mode="json"):
                return dict(self.payload)

        session = object.__new__(ProductionCognitiveSession)
        session._bootstrap_receipt = Dumpable(
            {"schema": "kaliv-consciousness-core/session-bootstrap-receipt/v1"}
        )
        session._live = SimpleNamespace(
            state=Dumpable(
                {
                    "schema": "kaliv-consciousness-core/self-state/v1",
                    "self_id": "self-" + "1" * 32,
                }
            )
        )
        session._continuity_state = None
        session._last_lived_continuity = None

        app = FastAPI()
        app.state.consciousness_session = session
        app.state.consciousness_sleep_wake_receipt = Dumpable(
            {"schema": "kaliv-consciousness-core/wake-receipt/v1"}
        )
        app.include_router(build_consciousness_status_router())
        loaded = SimpleNamespace(
            profile=Dumpable(
                {
                    "schema": "kaliv-consciousness-core/cognitive-profile/v1",
                    "profile_id": "cog-" + "2" * 32,
                }
            )
        )
        with patch.dict(
            os.environ,
            {"KALIV_CONSCIOUSNESS_EVIDENCE_EXPORT_ENABLED": "1"},
            clear=True,
        ), patch(
            "app.consciousness_core.status_api.load_cognitive_profile",
            return_value=loaded,
        ):
            response = TestClient(app).get(
                "/experimental/consciousness/evidence-snapshot"
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["schema"],
            "kaliv-consciousness-core/runtime-evidence-snapshot/v1",
        )
        self.assertEqual(body["model_calls"], 0)
        self.assertFalse(body["self_state_store_write_applied"])
        self.assertFalse(body["durable_memory_write_authority"])
        self.assertFalse(body["execution_authority"])
        self.assertFalse(body["scheduling_authority"])
        self.assertFalse(body["production_activation"])


if __name__ == "__main__":
    unittest.main()
