#!/usr/bin/env python3
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bodyrig_live_stream_probe import ProbeError, run_probe  # noqa: E402

BODY_ID = "bodyid-" + "a" * 24
PACKAGE_SHA = "b" * 64
SESSION_ID = "body-0123456789ab"
TOKEN = "probe-token-not-written-to-receipt"


class RigHandler(BaseHTTPRequestHandler):
    extra_unknown = False
    redirect_active = False
    redirect_followed = False
    wrong_body_header = False
    bad_session_header = False

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect-target":
            RigHandler.redirect_followed = True
            self.send_response(200)
            self.end_headers()
            return
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/api/v1/body/active":
            if self.redirect_active:
                host, port = self.server.server_address
                self.send_response(302)
                self.send_header("Location", f"http://{host}:{port}/redirect-target")
                self.end_headers()
                return
            payload = {
                "schema": "modelrig-body-assets/v1",
                "body_id": BODY_ID,
                "name": "Probe body",
                "package_sha256": PACKAGE_SHA,
                "source": "current",
                "avatar": "/body/active/avatar.vrm",
                "thumbnail": "/body/active/thumbnail.png",
                "motions": {},
                "payload_sizes": {},
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path.startswith("/api/v1/body/frames?"):
            fixture = json.loads(
                (
                    ROOT
                    / "renderers"
                    / "bodyrig-unity"
                    / "Assets"
                    / "BodyRig"
                    / "Resources"
                    / "bodyrig-demo.json"
                ).read_text(encoding="utf-8")
            )["frames"][0]
            chunks = []
            for index in range(5):
                frame = json.loads(json.dumps(fixture))
                frame["timestamp_ms"] = 1000 + index * 50
                if self.extra_unknown:
                    frame["renderer_bone"] = "Head"
                chunks.append("data: " + json.dumps(frame, separators=(",", ":")) + "\n\n")
            raw = "".join(chunks).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header(
                "X-BodyRig-Body-ID",
                "bodyid-" + "c" * 24 if self.wrong_body_header else BODY_ID,
            )
            self.send_header(
                "X-BodyRig-Session-ID",
                "not-a-session" if self.bad_session_header else SESSION_ID,
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(404)
        self.end_headers()


class LiveStreamProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        RigHandler.extra_unknown = False
        RigHandler.redirect_active = False
        RigHandler.redirect_followed = False
        RigHandler.wrong_body_header = False
        RigHandler.bad_session_header = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RigHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def run(self, *, body_id: str = BODY_ID) -> dict:
        return run_probe(
            base_url=self.base,
            token=TOKEN,
            expected_body_id=body_id,
            expected_package_sha256=PACKAGE_SHA,
            frame_count=5,
            timeout=3,
        )

    def test_authenticated_probe_validates_expected_body_frames_and_identity_headers(self) -> None:
        receipt = self.run()
        self.assertEqual(receipt["schema"], "bodyrig.live_stream_probe/v0.1")
        self.assertFalse(receipt["production_activation"])
        self.assertEqual(receipt["active_body_id"], BODY_ID)
        self.assertEqual(receipt["active_package_sha256"], PACKAGE_SHA)
        self.assertEqual(receipt["frame_count"], 5)
        self.assertEqual(receipt["frame_identity"], {"body_id": BODY_ID, "session_id": SESSION_ID})
        self.assertNotIn("slice_b_compatibility_extras", receipt)
        self.assertTrue(receipt["canonical_frame_validation"])
        self.assertNotIn(TOKEN, json.dumps(receipt))

    def test_wrong_token_fails_without_echoing_secret(self) -> None:
        with self.assertRaisesRegex(ProbeError, r"HTTP 401") as caught:
            run_probe(
                base_url=self.base,
                token="secret-that-must-not-be-echoed",
                expected_body_id=BODY_ID,
                expected_package_sha256=PACKAGE_SHA,
                frame_count=2,
                timeout=3,
            )
        self.assertNotIn("secret-that-must-not-be-echoed", str(caught.exception))

    def test_redirect_is_rejected_before_bearer_can_be_replayed(self) -> None:
        RigHandler.redirect_active = True
        with self.assertRaisesRegex(ProbeError, r"HTTP 302"):
            self.run()
        self.assertFalse(RigHandler.redirect_followed)

    def test_unknown_wire_field_fails_closed(self) -> None:
        RigHandler.extra_unknown = True
        with self.assertRaisesRegex(ProbeError, "canonical render_frame"):
            self.run()

    def test_wrong_body_header_fails_closed(self) -> None:
        RigHandler.wrong_body_header = True
        with self.assertRaisesRegex(ProbeError, "body header differs"):
            self.run()

    def test_bad_session_header_fails_closed(self) -> None:
        RigHandler.bad_session_header = True
        with self.assertRaisesRegex(ProbeError, "session header is missing or invalid"):
            self.run()

    def test_active_body_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(ProbeError, "active body differs"):
            self.run(body_id="bodyid-" + "c" * 24)


if __name__ == "__main__":
    unittest.main(verbosity=2)
