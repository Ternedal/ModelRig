#!/usr/bin/env python3
"""Snapshot operator errors are typed as the operator surface.

The A4-25f evidence finalizer requires the vendor media type on every
physical trial -- error stages included -- and the fixture host builds its
own FastAPI app around this router alone. A mount-time exception handler
would therefore never reach it, so the media type has to hold at the
source: every public error carries its own content-type header.

Two rig days (29-30/08) ended on "HTTP trace stage selected-root-404 media
type mismatch" because they did not.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agent4 import snapshot_operator_api as api  # noqa: E402


class SnapshotOperatorErrorMediaTypeTests(unittest.TestCase):
    def test_every_public_error_path_carries_the_operator_media_type(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "snapshot_operator_api.py"
        ).read_text(encoding="utf-8")
        start = source.index("def _raise_public(")
        block = source[start : source.index("\n\n\n", start)]
        raises = block.count("raise HTTPException(")
        headers = block.count("headers=_ERROR_HEADERS")
        self.assertGreaterEqual(raises, 4, "expected the public error mapping")
        self.assertEqual(
            raises,
            headers,
            "every public HTTPException must carry the operator media type",
        )

    def test_the_header_actually_reaches_the_rendered_error(self) -> None:
        # Pin the mechanism, not just the source: FastAPI renders
        # HTTPException as application/json unless the response carries its
        # own content-type.
        app = FastAPI()

        @app.get("/boom")
        def boom() -> dict[str, str]:
            raise HTTPException(
                status_code=404,
                detail="nope",
                headers={"content-type": api.SNAPSHOT_OPERATOR_MEDIA_TYPE},
            )

        response = TestClient(app, raise_server_exceptions=False).get("/boom")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            response.headers["content-type"].startswith(
                api.SNAPSHOT_OPERATOR_MEDIA_TYPE
            ),
            f"got {response.headers['content-type']!r}",
        )

    def test_the_media_type_matches_the_operator_surface(self) -> None:
        from app.agent4.operator_api import OPERATOR_MEDIA_TYPE

        self.assertEqual(api.SNAPSHOT_OPERATOR_MEDIA_TYPE, OPERATOR_MEDIA_TYPE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
