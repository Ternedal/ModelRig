#!/usr/bin/env python3
import json, os, signal, subprocess, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import os as _os
BIN = _os.environ.get("MODELRIG_BIN", "/tmp/modelrig-server")
OLLAMA_PORT = 11599

# ---- fake streaming Ollama --------------------------------------------------
class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({"models": [
                {"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        elif self.path == "/api/ps":
            body = json.dumps({"models": [
                {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b",
                 "size": 4700000000, "size_vram": 4700000000,
                 "expires_at": "2026-01-01T00:00:00Z"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path == "/api/chat":
            n = int(self.headers.get("Content-Length", "0")); self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for c in ["Hej", " fra", " ModelRig"]:
                self.wfile.write((json.dumps({"message": {"role": "assistant", "content": c}, "done": False}) + "\n").encode())
                self.wfile.flush(); time.sleep(0.05)
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n").encode())
            self.wfile.flush()
        elif self.path == "/api/pull":
            n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(n)
            global seen_pull_body
            seen_pull_body = body.decode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for line in [
                {"status": "pulling manifest"},
                {"status": "pulling digestabc", "digest": "digestabc", "total": 1000, "completed": 500},
                {"status": "pulling digestabc", "digest": "digestabc", "total": 1000, "completed": 1000},
                {"status": "verifying sha256 digest"},
                {"status": "success"},
            ]:
                self.wfile.write((json.dumps(line) + "\n").encode()); self.wfile.flush(); time.sleep(0.02)
        else:
            self.send_response(404); self.end_headers()
    def do_DELETE(self):
        if self.path == "/api/delete":
            n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(n)
            global seen_delete_body
            seen_delete_body = body.decode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", "2")
            self.end_headers(); self.wfile.write(b"{}")
        else:
            self.send_response(404); self.end_headers()

seen_pull_body = None
seen_delete_body = None

srv = HTTPServer(("127.0.0.1", OLLAMA_PORT), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()

passed = failed = 0
def check(cond, name):
    global passed, failed
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    passed += bool(cond); failed += (not cond)

def req(method, path, base, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    if body is not None: r.add_header("Content-Type", "application/json")
    if token: r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=8) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, str(e)

def start_server(port, data, extra_env=None):
    env = dict(os.environ, MODELRIG_HOST="127.0.0.1", MODELRIG_PORT=str(port),
               MODELRIG_DATA=data, MODELRIG_OLLAMA_URL=f"http://127.0.0.1:{OLLAMA_PORT}")
    if extra_env: env.update(extra_env)
    for f in (data, data + ".tmp"):
        try: os.remove(f)
        except FileNotFoundError: pass
    log = open(f"/tmp/mr-{port}.log", "w")
    return subprocess.Popen([BIN], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

# ============================ functional server ==============================
BASE = "http://127.0.0.1:8090"
p1 = start_server(8090, "/tmp/mr-v1.json")
try:
    time.sleep(1.2)

    # pair + token
    _, b = req("POST", "/api/v1/pair/start", BASE, body={})
    code = json.loads(b)["code"]
    s, b = req("POST", "/api/v1/pair/claim", BASE, body={"device_name": "laptop", "code": code})
    check(s == 200, "pair/claim -> 200")
    tok = json.loads(b)["token"]
    dev_id = json.loads(b)["device_id"]

    # models proxy (GET passthrough)
    s, b = req("GET", "/api/v1/models", BASE, token=tok)
    check(s == 200 and "qwen2.5-coder:7b" in b, "models proxy -> 200 + model names")

    # running models (GET /api/ps passthrough) -- distinct from installed-models list
    s, b = req("GET", "/api/v1/models/running", BASE, token=tok)
    check(s == 200 and "size_vram" in b, "models/running proxy -> 200 + size_vram present")

    # pull a model: request body reaches Ollama untouched, NDJSON progress streams through
    s, b = req("POST", "/api/v1/models/pull", BASE, token=tok, body={"model": "llama3.2:3b"})
    pull_lines = [json.loads(l) for l in b.strip().splitlines() if l.strip()]
    check(s == 200 and len(pull_lines) == 5, f"pull streams all progress lines -> got {len(pull_lines)}")
    check(pull_lines[-1].get("status") == "success", f"pull final line is success -> {pull_lines[-1] if pull_lines else None}")
    check(seen_pull_body == json.dumps({"model": "llama3.2:3b"}), f"pull request body forwarded untouched -> {seen_pull_body}")

    # delete a model: request body reaches Ollama untouched
    s, b = req("DELETE", "/api/v1/models/delete", BASE, token=tok, body={"model": "llama3.2:3b"})
    check(s == 200, "delete model -> 200")
    check(seen_delete_body == json.dumps({"model": "llama3.2:3b"}), f"delete request body forwarded untouched -> {seen_delete_body}")

    # auth still enforced on the new endpoints (no token -> 401)
    s, b = req("GET", "/api/v1/models/running", BASE, token=None)
    check(s == 401, "models/running without token -> 401")
    s, b = req("POST", "/api/v1/models/pull", BASE, token=None, body={"model": "x"})
    check(s == 401, "models/pull without token -> 401")
    s, b = req("DELETE", "/api/v1/models/delete", BASE, token=None, body={"model": "x"})
    check(s == 401, "models/delete without token -> 401")

    # streaming chat passthrough: all three NDJSON chunks arrive, in order
    s, b = req("POST", "/api/v1/chat", BASE, token=tok,
               body={"model": "qwen2.5-coder:7b", "messages": [{"role": "user", "content": "hej"}]})
    contents = []
    for line in b.strip().splitlines():
        try: contents.append(json.loads(line).get("message", {}).get("content", ""))
        except Exception: pass
    joined = "".join(contents)
    check(s == 200 and joined == "Hej fra ModelRig", f"chat NDJSON passthrough -> '{joined}'")

    # devices list: present, and NO token_hash leaked
    s, b = req("GET", "/api/v1/devices", BASE, token=tok)
    check(s == 200 and dev_id in b, "devices list -> 200 + contains device")
    check("token_hash" not in b, "devices list does NOT leak token_hash")

    # token rotation: new token works, old token dies, same device id
    s, b = req("POST", "/api/v1/token/rotate", BASE, token=tok)
    check(s == 200, "rotate -> 200")
    new_tok = json.loads(b)["token"]
    check(new_tok != tok, "rotate issues a different token")
    check(json.loads(b)["device_id"] == dev_id, "rotate keeps the same device id")
    s, _ = req("GET", "/api/v1/status", BASE, token=tok)
    check(s == 401, "old token invalid after rotation -> 401")
    s, _ = req("GET", "/api/v1/status", BASE, token=new_tok)
    check(s == 200, "new token valid after rotation -> 200")
    tok = new_tok  # continue with the rotated token

    # revoke device -> token immediately invalid
    s, _ = req("DELETE", f"/api/v1/devices/{dev_id}", BASE, token=tok)
    check(s == 200, "revoke device -> 200")
    s, _ = req("GET", "/api/v1/status", BASE, token=tok)
    check(s == 401, "revoked token -> 401 (revocation effective)")
    s, _ = req("DELETE", f"/api/v1/devices/{dev_id}", BASE, token=tok)
    check(s == 401, "revoked token cannot revoke again -> 401")

    # -pair CLI HTTP path: run the binary with -pair while server is up,
    # the printed code must be claimable (proves single-writer HTTP path)
    env = dict(os.environ, MODELRIG_PORT="8090")
    out = subprocess.run([BIN, "-pair"], env=env, capture_output=True, text=True, timeout=8).stdout
    cli_code = ""
    for line in out.splitlines():
        if "pairing code:" in line:
            cli_code = line.split(":", 1)[1].strip()
    check(bool(cli_code), f"-pair CLI printed a code ({cli_code or 'none'})")
    s, b = req("POST", "/api/v1/pair/claim", BASE, body={"device_name": "phone", "code": cli_code})
    check(s == 200, "code from -pair (running server) is claimable -> 200")

    print(f"\n  functional: {passed} passed, {failed} failed")
finally:
    try: os.killpg(os.getpgid(p1.pid), signal.SIGTERM); p1.wait(timeout=5)
    except Exception: pass

# ============================ rate-limit server ==============================
BASE2 = "http://127.0.0.1:8091"
p2 = start_server(8091, "/tmp/mr-rl.json", {"MODELRIG_CLAIM_MAX": "3"})
try:
    time.sleep(1.0)
    codes = []
    for i in range(6):
        s, _ = req("POST", "/api/v1/pair/claim", BASE2, body={"device_name": "x", "code": "AAAA-AAAA"})
        codes.append(s)
    # first 3 attempts allowed (401 unknown code), then 429
    check(codes[:3] == [401, 401, 401], f"first 3 claims allowed (401 unknown): {codes[:3]}")
    check(429 in codes[3:], f"claim throttled after limit -> 429 appears: {codes}")
    print(f"\n  rate-limit: {passed} passed, {failed} failed (cumulative)")
finally:
    try: os.killpg(os.getpgid(p2.pid), signal.SIGTERM); p2.wait(timeout=5)
    except Exception: pass
    srv.shutdown()

print(f"\n===== V1 SMOKE TOTAL: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
