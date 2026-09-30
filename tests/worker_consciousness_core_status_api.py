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


    def test_qualification_snapshot_is_default_off(self):
        app = FastAPI()
        app.include_router(build_consciousness_status_router())
        with patch.dict(os.environ, {}, clear=True):
            response = TestClient(app).get(
                "/experimental/consciousness/qualification-snapshot"
            )
        self.assertEqual(response.status_code, 404)

    def test_qualification_snapshot_exposes_only_explicit_local_evidence(self):
        import app.consciousness_core.status_api as status_api

        class Dumpable:
            def __init__(self, payload):
                self.payload = payload

            def model_dump(self, mode="json"):
                return dict(self.payload)

        class DummySession:
            bootstrap_receipt = Dumpable({"schema": "bootstrap:test"})
            lived_continuity = Dumpable({"schema": "lived:test"})
            live_state = SimpleNamespace(
                state=Dumpable({"schema": "self:test"})
            )

        app = FastAPI()
        app.state.consciousness_session = DummySession()
        app.state.consciousness_sleep_wake_receipt = Dumpable(
            {"schema": "wake:test"}
        )
        app.include_router(build_consciousness_status_router())

        profile = SimpleNamespace(
            profile=Dumpable({"schema": "profile:test"})
        )
        env = {"KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED": "1"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(status_api, "ProductionCognitiveSession", DummySession),
            patch.object(status_api, "load_cognitive_profile", return_value=profile),
        ):
            response = TestClient(app).get(
                "/experimental/consciousness/qualification-snapshot"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["schema"],
            "kaliv-consciousness-core/qualification-snapshot/v1",
        )
        self.assertRegex(
            body["runtime_instance_ref"],
            r"^runtime-instance:[0-9a-f]{32}$",
        )
        self.assertEqual(body["wake_receipt"]["schema"], "wake:test")
        self.assertEqual(
            body["session_bootstrap_receipt"]["schema"],
            "bootstrap:test",
        )
        self.assertEqual(body["self_state"]["schema"], "self:test")
        self.assertEqual(body["cognitive_profile"]["schema"], "profile:test")
        self.assertEqual(body["lived_continuity"]["schema"], "lived:test")
        self.assertFalse(body["production_activation"])


if __name__ == "__main__":
    unittest.main()
