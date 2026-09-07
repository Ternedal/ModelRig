#!/usr/bin/env python3
"""Runtime proof for #704 BodyRig default-off production activation."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI  # noqa: E402

from app import body_session  # noqa: E402
from app.bodyrig_activation import BODYRIG_FLAG, bodyrig_enabled  # noqa: E402
from app.bodyrig_mount import mount_bodyrig  # noqa: E402


class BodyRigProductionActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get(BODYRIG_FLAG)
        os.environ.pop(BODYRIG_FLAG, None)
        body_session._session = None

    def tearDown(self) -> None:
        body_session._session = None
        if self.previous is None:
            os.environ.pop(BODYRIG_FLAG, None)
        else:
            os.environ[BODYRIG_FLAG] = self.previous

    def test_production_mount_is_default_off_and_exact_opt_in(self) -> None:
        self.assertFalse(bodyrig_enabled())
        app = FastAPI()
        self.assertFalse(mount_bodyrig(app))
        self.assertFalse(any(path.startswith("/body") for path in app.openapi()["paths"]))

        for value in ("", "0", "true", "TRUE", "yes", "2", " 1x "):
            os.environ[BODYRIG_FLAG] = value
            self.assertFalse(bodyrig_enabled(), value)

        os.environ[BODYRIG_FLAG] = " 1 "
        self.assertTrue(bodyrig_enabled())
        enabled_app = FastAPI()
        self.assertTrue(mount_bodyrig(enabled_app))
        paths = set(enabled_app.openapi()["paths"])
        self.assertIn("/body/active", paths)
        self.assertIn("/body/frames", paths)
        route_count = len(enabled_app.routes)
        path_count = len(paths)
        self.assertTrue(mount_bodyrig(enabled_app))
        self.assertEqual(len(enabled_app.routes), route_count)
        self.assertEqual(len(enabled_app.openapi()["paths"]), path_count)

    def test_disabled_hooks_do_not_touch_runtime_or_wav(self) -> None:
        calls: list[bool] = []
        original = body_session.current_session
        try:
            def probe(create: bool = True):
                calls.append(create)
                raise AssertionError("default-off hook reached BodyRig runtime")

            body_session.current_session = probe
            body_session.note_state("thinking")
            body_session.note_speech(
                utterance_id="u-off",
                wav_path="/definitely/missing/bodyrig-off.wav",
            )
        finally:
            body_session.current_session = original
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
