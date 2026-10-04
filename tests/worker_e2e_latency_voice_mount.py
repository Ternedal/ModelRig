#!/usr/bin/env python3
"""Default-off mount contract for the #2063 voice qualification surface."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.e2e_latency_voice import FLAG, mount  # noqa: E402

PREFIX = "/experimental/e2e-latency"


def qualification_routes(app: FastAPI) -> list[object]:
    result: list[object] = []
    for route in app.routes:
        if type(route).__name__ == "_IncludedRouter":
            original = getattr(route, "original_router", None)
            candidates = getattr(original, "routes", ()) if original else ()
        else:
            candidates = (route,)
        for candidate in candidates:
            if str(getattr(candidate, "path", "")).startswith(PREFIX):
                result.append(candidate)
    return result


class E2ELatencyVoiceMountTests(unittest.TestCase):
    def test_mount_is_exact_default_off(self) -> None:
        for value in (None, "", "0", "true", "yes", "on", " 1 "):
            app = FastAPI()
            env = {} if value is None else {FLAG: value}
            with patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop(FLAG, None)
                self.assertFalse(mount(app), value)
            self.assertEqual(qualification_routes(app), [])

    def test_exact_opt_in_mounts_one_post_route_and_is_idempotent(self) -> None:
        app = FastAPI()
        with patch.dict(os.environ, {FLAG: "1"}, clear=False):
            self.assertTrue(mount(app))
            route_count = len(app.routes)
            self.assertTrue(mount(app))
        self.assertEqual(len(app.routes), route_count)
        routes = qualification_routes(app)
        self.assertEqual(len(routes), 1)
        self.assertEqual(getattr(routes[0], "methods", set()), {"POST"})
        self.assertEqual(
            str(getattr(routes[0], "path", "")),
            "/experimental/e2e-latency/voice",
        )

    def test_mount_creates_no_evidence_root_or_runtime_state(self) -> None:
        app = FastAPI()
        with patch.dict(
            os.environ,
            {
                FLAG: "1",
                "KALIV_E2E_LATENCY_EVIDENCE_ROOT": "/definitely/not/created/by/mount",
                "KALIV_E2E_LATENCY_CANDIDATE_GIT_SHA": "a" * 40,
            },
            clear=False,
        ):
            self.assertTrue(mount(app))
        self.assertFalse(
            hasattr(app.state, "consciousness_session"),
            "mount must not fabricate a runtime session",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
