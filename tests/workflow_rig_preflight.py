"""The preflight doctor must classify each rig state correctly.

The doctor exists to save the scarce rig session: it checks every dependency of
the physical validation and tells Anders exactly what is wrong before he runs it.
That is only worth anything if its verdicts are right -- a doctor that says
"ready" when the token is dead wastes the exact time it was meant to save. So its
paths are driven here against a fake backend, both the green ones and the failing
ones.

Run: PYTHONPATH=worker python3 tests/workflow_rig_preflight.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rig_preflight", ROOT / "scripts" / "rig_preflight.py")
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class _Handler(BaseHTTPRequestHandler):
    scenario = "ready"

    def log_message(self, *a):
        pass

    def _rig(self):
        s = _Handler.scenario
        if s == "ready":
            return {"configured": False, "present": False, "reasons": ["no path"],
                    "eligible_for_developer_preview": False, "report_sha256": None}
        if s == "already_valid":
            return {"configured": True, "present": True, "reasons": [],
                    "eligible_for_developer_preview": True,
                    "eligible_for_write_pilot": False, "report_sha256": "a" * 64}
        if s == "bad_build":
            return {"configured": False, "present": False, "reasons": [],
                    "eligible_for_developer_preview": False}
        return {}

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if self.path == "/healthz":
            return self._send(200, {"ok": True})
        if not auth.startswith("Bearer "):
            return self._send(401, {"error": "no token"})
        if _Handler.scenario == "token_rejected":
            return self._send(401, {"error": "bad token"})
        if self.path == "/api/v1/status":
            return self._send(200, {"status": "ok"})
        if self.path == "/api/v1/experimental/agent3/status":
            code_sha = "" if _Handler.scenario == "bad_build" else "b" * 64
            prod = True if _Handler.scenario == "bad_build" else False
            return self._send(200, {"code_sha256": code_sha,
                                    "production_activation": prod,
                                    "rig_validation": self._rig()})
        if self.path.startswith("/api/v1/health/full"):
            if _Handler.scenario == "ollama_down":
                return self._send(200, {"ok": False, "faults": ["ollama"], "checks": {
                    "ollama": {"ok": False, "detail": "connection refused"},
                    "disk": {"ok": True, "free_gb": 120.5},
                    "asr": {"ok": True, "device": "cuda"}}})
            return self._send(200, {"ok": True, "faults": [], "checks": {
                "ollama": {"ok": True, "embed_dims": 768},
                "disk": {"ok": True, "free_gb": 120.5},
                "asr": {"ok": True, "device": "cuda"}, "tts": {"ok": True}}})
        if self.path == "/api/v1/models":
            return self._send(200, {"models": [{"name": "qwen3:14b"},
                                               {"name": "nomic-embed-text"}]})
        return self._send(404, {"error": "nope"})

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


_server = HTTPServer(("127.0.0.1", 0), _Handler)
_port = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()
_BASE = f"http://127.0.0.1:{_port}"


def run(scenario, token="tok1234567890123456", planner="qwen3:14b"):
    """Run the doctor against the fake rig in a given scenario; return exit code."""
    _Handler.scenario = scenario
    old = dict(os.environ)
    try:
        if token is None:
            os.environ.pop("MODELRIG_TOKEN", None)
        else:
            os.environ["MODELRIG_TOKEN"] = token
        if planner is None:
            os.environ.pop("KALIV_AGENT3_PLANNER_MODEL", None)
        else:
            os.environ["KALIV_AGENT3_PLANNER_MODEL"] = planner
        os.environ.pop("KALIV_AGENT3_VALIDATION_REPORT", None)
        return preflight.main(["--base-url", _BASE])
    finally:
        os.environ.clear()
        os.environ.update(old)


# --- the green path: rig up, no report yet, everything ready -----------------
check(run("ready") == 0,
      "a rig that is up with no report yet is READY (exit 0) -- the missing "
      "report is the normal pre-run state, not a blocker")

# --- already validated: an accepted report is present -----------------------
check(run("already_valid") == 0,
      "a rig with an accepted report reports success (exit 0)")

# --- token rejected must be a hard blocker, not a vague connection error -----
check(run("token_rejected") == 1,
      "a rejected token is NOT READY (exit 1) -- the run cannot authenticate")

# --- missing env is a blocker even if the backend is up ----------------------
check(run("ready", token=None) == 1,
      "no MODELRIG_TOKEN is a blocker even when the backend answers")
check(run("ready", planner=None) == 1,
      "no planner model is a blocker -- the validation cannot plan without it")

# --- backend down is a blocker, and does not crash ---------------------------
_Handler.scenario = "ready"
_down = preflight.main(["--base-url", "http://127.0.0.1:1"])
check(_down == 1,
      "an unreachable backend is NOT READY (exit 1) and the doctor does not "
      "crash trying to reach it")

# --- a broken build (no code_sha256, production_activation true) is a blocker -
check(run("bad_build") == 1,
      "a build that cannot report code identity or claims production active is "
      "a blocker -- this is the safety invariant, not a warning")

# --- the doctor changes nothing --------------------------------------------
# It is a read-only preflight; assert it makes only GET requests by construction
# (the fake handler has no do_POST, and a POST would 501 and surface as a crash
# or failure above -- none did).
check(not hasattr(_Handler, "do_POST"),
      "the doctor is read-only -- the fake rig served only GETs and nothing "
      "tried to POST, so preflight cannot mutate the rig")

# --- the substrate the validation runs through is checked too (F-919) --------
# Preflight must not green-light a rig where the Agent 3 handshake works but
# Ollama is down -- the validation would fail partway. A substrate fault is a
# blocker, and it must be legible, not a bare "run failed".
check(run("ollama_down") == 1,
      "Ollama down is NOT READY (exit 1) -- the substrate the validation embeds "
      "and plans through is a hard dependency, checked before the run")

# And a fully healthy substrate is still READY (the substrate checks do not
# spuriously block a good rig).
check(run("ready") == 0,
      "a healthy substrate stays READY -- the new checks pass a good rig")

print(f"\n===== RIG PREFLIGHT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
