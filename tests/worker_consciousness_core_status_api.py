from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.consciousness_core.status_api import build_consciousness_status_router


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
        ):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
