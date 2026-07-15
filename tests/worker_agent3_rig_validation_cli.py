from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "agent3_rig_validation", Path("scripts/agent3_rig_validation.py")
)
assert spec and spec.loader
validation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validation
spec.loader.exec_module(validation)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[tuple[str, str]] = []
    memory_value = ""
    marker = ""
    write_started = False
    write_decision = ""

    def log_message(self, _format, *_args):
        pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _reply(self, status: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self) -> bool:
        if self.headers.get("Authorization") != "Bearer test-token":
            self._reply(401, {"error": "invalid token"})
            return False
        assert self.headers.get("X-Request-ID", "").startswith(
            "agent3-rig-validation-"
        )
        return True

    @classmethod
    def _context(cls) -> str:
        return "----- BEGIN KALIV MEMORY DATA -----\n" + cls.memory_value + "\n----- END KALIV MEMORY DATA -----"

    @classmethod
    def _receipt(cls) -> dict:
        text = cls._context()
        return {
            "requested": True,
            "sent_to_model": True,
            "target": "local",
            "included_ids": ["memory/1"],
            "excluded_ids": [],
            "character_count": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def do_GET(self):
        type(self).calls.append(("GET", self.path))
        if not self._auth():
            return
        if self.path == "/api/v1/experimental/agent3/status":
            self._reply(
                200,
                {
                    "enabled": True,
                    "experimental": True,
                    "production_tools_path_untouched": True,
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/runs/read%2F1/events":
            self._reply(
                200,
                {
                    "events": [
                        {"kind": "run_created"},
                        {"kind": "policy_decision"},
                        {"kind": "step_started"},
                        {"kind": "step_succeeded"},
                        {"kind": "run_completed"},
                    ]
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/runs/write%2F1/events":
            kinds = ["run_created", "policy_decision", "confirmation_required"]
            if type(self).write_decision == "deny":
                kinds.append("confirmation_denied")
            self._reply(200, {"events": [{"kind": kind} for kind in kinds]})
            return
        self._reply(404, {"error": "not found"})

    def do_POST(self):
        type(self).calls.append(("POST", self.path))
        if not self._auth():
            return
        body = self._body()
        if self.path == "/api/v1/experimental/agent3/memory":
            type(self).memory_value = body["value"]
            match = re.search(r"KALIV_AGENT3_VALIDATION_[0-9a-f]+", body["value"])
            assert match
            type(self).marker = match.group(0)
            self._reply(
                200,
                {
                    "memory": {
                        "id": "memory/1",
                        "review_status": "confirmed",
                        "lifecycle_status": "active",
                        "sensitivity": "operational",
                    }
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/memory/context-preview":
            assert body["target"] == "local"
            assert len(body["subjects"]) == 1
            text = type(self)._context()
            self._reply(
                200,
                {
                    "target": "local",
                    "included_ids": ["memory/1"],
                    "excluded_ids": [],
                    "character_count": len(text),
                    "text": text,
                    "sent_to_model": False,
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/plan":
            assert body["use_memory"] is True
            assert body["mode"] == "rig"
            receipt = type(self)._receipt()
            if "rig_status" in body["message"]:
                self._reply(
                    200,
                    {
                        "executed": False,
                        "plan_id": "read/plan",
                        "memory_context": receipt,
                        "plan": [
                            {
                                "tool": "rig_status",
                                "args": {},
                                "risk": "read",
                                "sensitivity": "operational",
                                "egress": "local",
                            }
                        ],
                    },
                )
            else:
                self._reply(
                    200,
                    {
                        "executed": False,
                        "plan_id": "write/plan",
                        "memory_context": receipt,
                        "plan": [
                            {
                                "tool": "note_append",
                                "args": {"text": type(self).marker},
                                "risk": "write",
                                "sensitivity": "private",
                                "egress": "local",
                            }
                        ],
                    },
                )
            return
        if self.path == "/api/v1/experimental/agent3/plans/read%2Fplan/start":
            self._reply(
                200,
                {
                    "memory_context": type(self)._receipt(),
                    "run": {
                        "id": "read/1",
                        "state": "completed",
                        "current_step": 1,
                        "steps": [
                            {"tool": "rig_status", "state": "succeeded"}
                        ],
                    },
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/plans/write%2Fplan/start":
            if type(self).write_started:
                self._reply(409, {"detail": "plan already consumed"})
                return
            type(self).write_started = True
            self._reply(
                200,
                {
                    "memory_context": type(self)._receipt(),
                    "run": {
                        "id": "write/1",
                        "state": "waiting_confirmation",
                        "current_step": 0,
                        "steps": [
                            {
                                "id": "step/1",
                                "tool": "note_append",
                                "args": {"text": type(self).marker},
                                "risk": "write",
                                "state": "waiting_confirmation",
                                "summary": "Append validation marker",
                                "confirmation_digest": "d" * 64,
                                "confirmation_expires_at": time.time() + 60,
                            }
                        ],
                    },
                },
            )
            return
        if self.path == "/api/v1/experimental/agent3/runs/write%2F1/confirm":
            assert body["step_id"] == "step/1"
            assert body["digest"] == "d" * 64
            assert body["decision"] == "deny"
            type(self).write_decision = "deny"
            self._reply(
                200,
                {
                    "run": {
                        "id": "write/1",
                        "state": "cancelled",
                        "current_step": 0,
                        "steps": [
                            {
                                "id": "step/1",
                                "tool": "note_append",
                                "state": "denied",
                            }
                        ],
                    }
                },
            )
            return
        self._reply(404, {"error": "not found"})

    def do_DELETE(self):
        type(self).calls.append(("DELETE", self.path))
        if not self._auth():
            return
        if self.path == "/api/v1/experimental/agent3/memory/memory%2F1":
            self._reply(
                200,
                {
                    "memory": {
                        "id": "memory/1",
                        "value": "",
                        "source_ref": None,
                        "review_status": "rejected",
                        "lifecycle_status": "deleted",
                    }
                },
            )
            return
        self._reply(404, {"error": "not found"})


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    root = Path(tempfile.mkdtemp(prefix="agent3-rig-validation-test-"))
    report_path = root / "report.json"
    report = validation.run_validation(
        validation.Client(
            f"http://127.0.0.1:{server.server_port}", "test-token", 5
        ),
        planner_model="fake-local-planner",
        approve_write=False,
        report_path=report_path,
        poll_seconds=0.01,
        max_wait_seconds=1,
    )
    assert report["success"] is True
    assert report["checks"]["write_confirmation"]["decision"] == "deny"
    assert report["checks"]["write_confirmation"]["mutation_expected"] is False
    assert report["checks"]["single_use"]["replay_blocked"] is True
    assert report["cleanup"]["deleted"] is True
    report_text = report_path.read_text(encoding="utf-8")
    assert "test-token" not in report_text
    assert Handler.memory_value not in report_text
    assert Handler.marker not in report_text
    assert validation.main(["--token", ""]) == 2
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

print("9 passed, 0 failed")
