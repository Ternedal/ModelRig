from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


spec = importlib.util.spec_from_file_location("agent3_smoke", Path("scripts/agent3_smoke.py"))
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
# dataclasses resolves postponed annotations through sys.modules while the class
# decorator runs. Register the dynamically loaded module before exec_module,
# exactly as Python's normal import machinery does.
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[tuple[str, str]] = []

    def log_message(self, _format, *_args):
        pass

    def _reply(self, status: int, payload: dict):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self) -> bool:
        if self.headers.get("Authorization") != "Bearer test-token":
            self._reply(401, {"error": "invalid token"})
            return False
        assert self.headers.get("X-Request-ID", "").startswith("agent3-smoke-")
        return True

    def do_GET(self):
        type(self).calls.append(("GET", self.path))
        if not self._auth():
            return
        if self.path == "/api/v1/experimental/agent3/status":
            self._reply(200, {"enabled": True, "experimental": True})
            return
        if self.path == "/api/v1/experimental/agent3/runs/run%2F1/events":
            self._reply(
                200,
                {
                    "events": [
                        {"kind": "run_created"},
                        {"kind": "step_started"},
                        {"kind": "step_succeeded"},
                        {"kind": "run_completed"},
                    ]
                },
            )
            return
        self._reply(404, {"error": "not found"})

    def do_POST(self):
        type(self).calls.append(("POST", self.path))
        if not self._auth():
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/v1/experimental/agent3/plan":
            assert body["mode"] == "rig"
            self._reply(
                200,
                {
                    "executed": False,
                    "plan_id": "plan/1",
                    "plan": [
                        {
                            "tool": "rig_status",
                            "args": {},
                            "risk": "read",
                            "sensitivity": "operational",
                            "egress": "local",
                            "summary": "Læs rigstatus",
                        }
                    ],
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/plans/plan%2F1/start":
            assert body == {}
            self._reply(
                200,
                {
                    "run": {
                        "id": "run/1",
                        "state": "completed",
                        "steps": [{"tool": "rig_status", "state": "succeeded", "result": {"ok": True}}],
                    }
                },
            )
            return
        self._reply(404, {"error": "not found"})


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = smoke.run_smoke(
        smoke.Client(f"http://127.0.0.1:{server.server_port}", "test-token", 5),
        message="Brug rig_status",
        poll_seconds=0.01,
        max_wait_seconds=1,
    )
    assert result["run"]["state"] == "completed"
    assert ("POST", "/api/v1/experimental/agent3/plans/plan%2F1/start") in Handler.calls
    assert ("GET", "/api/v1/experimental/agent3/runs/run%2F1/events") in Handler.calls
    assert smoke.main(["--base-url", "http://127.0.0.1:9", "--token", ""]) == 2
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

print("4 passed, 0 failed")
