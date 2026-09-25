#!/usr/bin/env python3
"""C31-B VisionRig explicit loopback transport tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.visionrig_transport import (  # noqa: E402
    VisionRigClient,
    VisionRigTransportError,
)


class VisionRigTransportTests(unittest.TestCase):
    def event(self):
        return {
            "schema_id": "visionrig/perception-event/v2",
            "event_id": "evt-test",
            "observed_at": "2026-09-25T12:00:00+00:00",
            "source": {
                "source_id": "camera-0",
                "source_type": "camera",
                "device": "0",
            },
            "frame_sequence": 7,
            "entities": [],
            "relations": [],
            "landmarks": [],
            "depth": [],
            "scene_label": None,
            "scene_confidence": None,
            "dropped_frames": 0,
            "production_authority": False,
        }

    def test_client_is_loopback_only(self):
        with self.assertRaises(VisionRigTransportError):
            VisionRigClient("http://example.com:8110")

    def test_client_parses_bounded_event_batch(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/v1/perception/events")
            return httpx.Response(
                200,
                json={
                    "schema_id": "visionrig/event-batch/v1",
                    "entries": [{"cursor": 8, "event": self.event()}],
                    "next_cursor": 8,
                    "oldest_available_cursor": 1,
                    "newest_available_cursor": 8,
                    "gap": False,
                },
            )

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as raw:
            client = VisionRigClient("http://127.0.0.1:8110", client=raw)
            batch = client.fetch_events(after_cursor=7)
        self.assertEqual(batch.next_cursor, 8)
        self.assertEqual(batch.entries[0].event.frame_sequence, 7)

    def test_gap_is_preserved_for_fail_closed_caller(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "schema_id": "visionrig/event-batch/v1",
                    "entries": [],
                    "next_cursor": 7,
                    "oldest_available_cursor": 20,
                    "newest_available_cursor": 30,
                    "gap": True,
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as raw:
            batch = VisionRigClient(client=raw).fetch_events(after_cursor=7)
        self.assertTrue(batch.gap)

    def test_malformed_batch_fails_closed(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps({"unexpected": True}))

        with httpx.Client(transport=httpx.MockTransport(handler)) as raw:
            client = VisionRigClient(client=raw)
            with self.assertRaises(VisionRigTransportError):
                client.fetch_events(after_cursor=0)


if __name__ == "__main__":
    unittest.main()
