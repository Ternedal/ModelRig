#!/usr/bin/env python3
"""End-to-end integration test for the ModelRig server stack.

Starts the REAL Go backend and the REAL Python worker (with a fake Ollama), then
drives the whole flow through the reference CLI: pair -> models -> chat (stream)
-> rag-ingest -> rag-query -> devices -> revoke. Proves the backend<->worker<->
Ollama chain works together, not just each piece in isolation.

Run:  python3 tests/e2e.py   (from the repo root)
Requires: the backend binary at /tmp/modelrig-server, worker deps installed.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.environ.get("MODELRIG_BIN", "/tmp/modelrig-server")
CLI = os.path.join(REPO, "tools", "modelrig-cli.py")
CFG = "/tmp/e2e-cli.json"
OLLAMA_PORT, WORKER_PORT, BACKEND_PORT = 11600, 8099, 8080
BACKEND = f"http://127.0.0.1:{BACKEND_PORT}"


# ---------------- fake Ollama (tags + chat stream/non-stream + embeddings) ----
def _vec(text):
    v = [0.0] * 26
    for ch in text.lower():
        i = ord(ch) - 97
        if 0 <= i < 26:
            v[i] += 1.0
    return v


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/embeddings":
            self._json({"embedding": _vec(payload.get("prompt", ""))})
        elif self.path == "/api/chat":
            if payload.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for c in ["stream", "-", "ok"]:
                    self.wfile.write((json.dumps({"message": {"role": "assistant", "content": c}, "done": False}) + "\n").encode())
                    self.wfile.flush()
                    time.sleep(0.03)
                self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
                self.wfile.flush()
            else:
                self._json({"message": {"role": "assistant", "content": "SYNTH-ANSWER"}, "done": True})
        else:
            self.send_response(404)
            self.end_headers()


# ---------------- helpers ----------------------------------------------------
passed = failed = 0
def check(cond, name):
    global passed, failed
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    passed += bool(cond); failed += (not cond)


def wait_health(url, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def cli(*args):
    return subprocess.run([sys.executable, CLI, "--config", CFG, *args],
                          capture_output=True, text=True, timeout=60)


def main():
    for f in (CFG, "/tmp/e2e-worker.db", "/tmp/e2e-backend.json", "/tmp/e2e-backend.json.tmp"):
        try: os.remove(f)
        except FileNotFoundError: pass

    srv = HTTPServer(("127.0.0.1", OLLAMA_PORT), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    fake = f"http://127.0.0.1:{OLLAMA_PORT}"
    worker = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(WORKER_PORT)],
        cwd=os.path.join(REPO, "worker"),
        env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "worker"),
                 MODELRIG_OLLAMA_URL=fake, MODELRIG_DB="/tmp/e2e-worker.db"),
        stdout=open("/tmp/e2e-worker.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)

    backend = subprocess.Popen(
        [BIN],
        env=dict(os.environ, MODELRIG_HOST="127.0.0.1", MODELRIG_PORT=str(BACKEND_PORT),
                 MODELRIG_OLLAMA_URL=fake, MODELRIG_WORKER_URL=f"http://127.0.0.1:{WORKER_PORT}",
                 MODELRIG_DATA="/tmp/e2e-backend.json"),
        stdout=open("/tmp/e2e-backend.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)

    try:
        check(wait_health(f"http://127.0.0.1:{WORKER_PORT}"), "worker healthy")
        check(wait_health(BACKEND), "backend healthy")

        # mint a pairing code directly, then pair via the CLI
        with urllib.request.urlopen(urllib.request.Request(
                BACKEND + "/api/v1/pair/start", data=b"{}", method="POST"), timeout=5) as r:
            code = json.loads(r.read())["code"]

        p = cli("--url", BACKEND, "pair", "--code", code, "--name", "e2e")
        check(p.returncode == 0 and "paired as" in p.stdout, "CLI pair -> ok")

        p = cli("whoami")
        check(p.returncode == 0 and "token=" in p.stdout, "CLI whoami shows saved token")

        p = cli("models")
        check(p.returncode == 0 and "qwen2.5-coder:7b" in p.stdout, "CLI models (proxy /api/tags)")

        p = cli("chat", "hello there")
        check(p.returncode == 0 and p.stdout.strip() == "stream-ok", f"CLI streaming chat -> '{p.stdout.strip()}'")

        p = cli("rag-ingest", "ModelRig binds zero point zero point zero point zero for LAN access",
                "--source", "docs")
        ok = p.returncode == 0 and json.loads(p.stdout).get("chunks_added", 0) >= 1
        check(ok, "CLI rag-ingest through backend -> chunks stored")

        p = cli("rag-query", "what does it bind for LAN", "--no-synth", "--top-k", "3")
        matches = json.loads(p.stdout).get("matches", []) if p.returncode == 0 else []
        check(len(matches) >= 1 and matches[0].get("source") == "docs", "CLI rag-query (matches only) via backend->worker")

        p = cli("rag-query", "what does it bind", "--top-k", "2")
        check(p.returncode == 0 and json.loads(p.stdout).get("answer") == "SYNTH-ANSWER",
              "CLI rag-query with synthesis -> answer from (fake) Ollama")

        p = cli("devices")
        check(p.returncode == 0 and "e2e" in p.stdout, "CLI devices lists the paired device")

        dev_id = json.loads(open(CFG).read())["device_id"]
        p = cli("revoke", dev_id)
        check(p.returncode == 0 and "revoked" in p.stdout, "CLI revoke -> ok")

        p = cli("models")  # token now revoked -> should fail
        check(p.returncode != 0, "CLI call after revoke fails (token invalidated)")

        print(f"\n===== E2E: {passed} passed, {failed} failed =====")
    finally:
        for proc in (backend, worker):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        srv.shutdown()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
