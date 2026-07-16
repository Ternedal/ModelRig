"""Jobs (F-004): a long action can no longer die silently.

Runs the REAL pull-job body against a fake streaming Ollama and pins the
terminal-truth contract: completed requires success + the model on the shelf;
anything else is failed/cancelled WITH a reason; a worker restart marks
in-flight jobs interrupted.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

_TMP = tempfile.mkdtemp(prefix="kaliv_jobs_")
os.environ["MODELRIG_JOBS_DB"] = os.path.join(_TMP, "jobs.db")

SCENARIO = {"pull": "ok", "tags_has_model": True}


class _ClientGone(Exception):
    """The pull client cancelled and closed -- expected in the cancel test."""
MODEL = "testmodel:1b"


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        if self.path != "/api/pull":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def line(obj):
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise _ClientGone

        mode = SCENARIO["pull"]
        try:
            self._stream(mode, line)
        except _ClientGone:
            pass

    def _stream(self, mode, line):
        if mode == "ok":
            line({"status": "pulling manifest"})
            line({"status": "downloading", "completed": 1, "total": 2})
            line({"status": "success"})
        elif mode == "cut":
            line({"status": "downloading", "completed": 1, "total": 9})
            # die without success -- like a severed connection
        elif mode == "error":
            line({"status": "downloading"})
            line({"error": "manifest unknown"})
        elif mode == "slow":
            for i in range(40):
                line({"status": "downloading", "completed": i, "total": 40})
                time.sleep(0.2)
            line({"status": "success"})

    def do_GET(self):
        if self.path != "/api/tags":
            self.send_error(404)
            return
        models = [{"name": MODEL}] if SCENARIO["tags_has_model"] else []
        body = json.dumps({"models": models}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["MODELRIG_OLLAMA_URL"] = f"http://127.0.0.1:{srv.server_port}"

from app.tools import REGISTRY, _get_jobstore, _run_cancel_job, _run_job_status, _run_pull_model  # noqa: E402
from app.jobs import JobStore  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def job_id_from(text: str) -> str:
    return text.split("som job ", 1)[1].split(".")[0].strip()


def wait_terminal(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = _get_jobstore().get(job_id)
        if j and j["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.1)
    return _get_jobstore().get(job_id) or {}


# registry contract
check(REGISTRY["pull_model"].risk == "write", "pull_model stays write-gated")
check(REGISTRY["job_status"].risk == "read", "job_status is a read tool")
check(REGISTRY["cancel_job"].risk == "write", "cancel_job is write-gated")

# A: happy path -- success line + model on the shelf => completed
SCENARIO.update(pull="ok", tags_has_model=True)
jid = job_id_from(_run_pull_model({"name": MODEL}))
j = wait_terminal(jid)
check(j.get("status") == "completed", f"ok pull -> completed (got {j.get('status')}: {j.get('detail')})")
check("verificeret" in j.get("detail", ""), "completed detail says verified")
check(j.get("progress_total", 0) > 0, "progress was recorded along the way")
check(jid in _run_job_status({"job_id": jid}), "job_status shows the job by id")

# B: stream ends without success => failed with the honest reason
SCENARIO.update(pull="cut")
j = wait_terminal(job_id_from(_run_pull_model({"name": MODEL})))
check(j.get("status") == "failed", "cut stream -> failed")
check("uden Ollamas 'success'" in j.get("detail", ""), "cut detail names the missing terminal line")

# C: in-stream error => failed with ollama's reason
SCENARIO.update(pull="error")
j = wait_terminal(job_id_from(_run_pull_model({"name": MODEL})))
check(j.get("status") == "failed" and "manifest unknown" in j.get("detail", ""),
      "in-stream error surfaces as the failure reason")

# D: success but model NOT in tags => failed (shelf verification)
SCENARIO.update(pull="ok", tags_has_model=False)
j = wait_terminal(job_id_from(_run_pull_model({"name": MODEL})))
check(j.get("status") == "failed" and "findes ikke" in j.get("detail", ""),
      "success without the model on the shelf is a failure, not a lie")

# E: cooperative cancel during a slow pull
SCENARIO.update(pull="slow", tags_has_model=True)
jid = job_id_from(_run_pull_model({"name": MODEL}))
deadline = time.time() + 5
while time.time() < deadline and (_get_jobstore().get(jid) or {}).get("status") != "running":
    time.sleep(0.05)
out = _run_cancel_job({"job_id": jid})
check("anmodet" in out, "cancel_job acknowledges the request")
j = wait_terminal(jid)
check(j.get("status") == "cancelled", f"slow pull cancels cooperatively (got {j.get('status')})")

# F: restart truth -- opening the store marks in-flight jobs interrupted
p2 = os.path.join(_TMP, "restart.db")
s1 = JobStore(p2)
rid = s1.create("pull_model", "x")
s1.update(rid, status="running")
s2 = JobStore(p2)  # "new process"
check(s2.get(rid)["status"] == "interrupted", "restart marks running jobs interrupted")
check("genstartet" in s2.get(rid)["detail"], "interrupted detail explains why")

# terminal immutability
s2.update(rid, status="completed")
check(s2.get(rid)["status"] == "interrupted", "terminal states are immutable")

srv.shutdown()
print(f"\n===== WORKER JOBS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
