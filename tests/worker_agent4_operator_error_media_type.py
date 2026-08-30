#!/usr/bin/env python3
"""The operator API types its ERROR responses like its successes.

Success bodies always carried application/vnd.modelrig.agent4.operator+json,
but HTTPException bodies fell back to FastAPI's application/json. Two
consequences, one of them expensive: an operator 404 was indistinguishable
from a proxy's 404, and the A4-25f evidence finalizer -- which requires the
vendor media type on every physical trial, error stages included -- could
never pass. That blocked Agent 4 qualification on the rig (30/08, #794).

This gate pins the behaviour so the media type cannot silently regress on
either path.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agent4.operator_api import OPERATOR_MEDIA_TYPE  # noqa: E402
from app.agent4.operator_read_context import (  # noqa: E402
    compose_agent4_operator_read_context,
)
from app.agent4.production_mount import mount_agent4_operator  # noqa: E402

PREFIX = "/experimental/agent4/operator"


class OperatorErrorMediaTypeTests(unittest.TestCase):
    def _client(self, directory: str) -> TestClient:
        context = compose_agent4_operator_read_context(Path(directory) / "runtime")
        app = FastAPI()
        with patch.dict(os.environ, {"KALIV_AGENT4_OPERATOR_API": "1"}, clear=False):
            self.assertTrue(mount_agent4_operator(app, context))
        return TestClient(app)

    def test_unknown_campaign_404_carries_the_operator_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            response = client.get(f"{PREFIX}/campaigns/does-not-exist")
            self.assertEqual(response.status_code, 404)
            self.assertTrue(
                response.headers["content-type"].startswith(OPERATOR_MEDIA_TYPE),
                f"error responses must be typed as the operator surface, got "
                f"{response.headers['content-type']!r}",
            )

    def test_invalid_query_422_carries_the_operator_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            response = client.get(f"{PREFIX}/campaigns", params=[("limit", "-5")])
            self.assertGreaterEqual(response.status_code, 400)
            self.assertTrue(
                response.headers["content-type"].startswith(OPERATOR_MEDIA_TYPE),
                f"error responses must be typed as the operator surface, got "
                f"{response.headers['content-type']!r}",
            )

    def test_routes_outside_the_operator_surface_keep_plain_json_errors(self) -> None:
        # The handler is scoped by path: it must not retype the rest of the
        # worker's errors as an Agent 4 operator payload.
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            response = client.get("/experimental/agent4/not-a-route")
            self.assertEqual(response.status_code, 404)
            self.assertFalse(
                response.headers["content-type"].startswith(OPERATOR_MEDIA_TYPE),
                "only operator-surface errors carry the vendor media type",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
