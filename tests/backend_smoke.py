#!/usr/bin/env python3
import json, os, signal, subprocess, sys, time, urllib.request, urllib.error

import os as _os
BIN = _os.environ.get("MODELRIG_BIN", "/tmp/modelrig-server")
DATA = "/tmp/mr-data.json"
BASE = "http://127.0.0.1:8080"

for f in (DATA, DATA + ".tmp"):
    try: os.remove(f)
    except FileNotFoundError: pass

env = dict(os.environ, MODELRIG_HOST="127.0.0.1", MODELRIG_PORT="8080", MODELRIG_DATA=DATA)
log = open("/tmp/mr-server.log", "w")
proc = subprocess.Popen([BIN], env=env, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True)

passed = failed = 0
def check(got, want, name):
    global passed, failed
    ok = str(got) == str(want)
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" (expected {want}, got {got})"))
    if ok: passed += 1
    else: failed += 1

def req(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if body is not None: r.add_header("Content-Type", "application/json")
    if token: r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=8) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, str(e)

try:
    time.sleep(1.2)

    s, b = req("GET", "/healthz");                         check(s, 200, "GET /healthz -> 200"); print("   ", b.strip())
    s, _ = req("GET", "/api/v1/status");                   check(s, 401, "status without token -> 401")

    s, b = req("POST", "/api/v1/pair/start", body={});     check(s, 200, "pair/start -> 200")
    code = json.loads(b)["code"]; print("    minted code:", code)

    s, b = req("POST", "/api/v1/pair/claim", body={"device_name": "anders-laptop", "code": code})
    check(s, 200, "pair/claim -> 200")
    tok = json.loads(b)["token"]
    check(len(tok), 64, "issued token is 64 hex chars")

    s, b = req("GET", "/api/v1/status", token=tok);        check(s, 200, "status with valid token -> 200")
    print("    status:", b.strip())

    s, _ = req("POST", "/api/v1/pair/claim", body={"device_name": "x", "code": code})
    check(s, 401, "reused pairing code -> 401 (single-use)")

    s, _ = req("GET", "/api/v1/status", token="deadbeefdeadbeef")
    check(s, 401, "garbage token -> 401")

    s, b = req("GET", "/api/v1/models", token=tok);        check(s, 502, "models proxy, ollama down -> 502 (upstream reached)")

    s, _ = req("POST", "/api/v1/pair/claim", body={"device_name": "y", "code": "ZZZZ-ZZZZ"})
    check(s, 401, "unknown code -> 401")

    s, _ = req("POST", "/api/v1/pair/claim", body={"device_name": "y", "code": "bad"})
    check(s, 400, "malformed code -> 400")

    print(f"\n===== SMOKE: {passed} passed, {failed} failed =====")
finally:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        pass

print("\n----- persisted store -----")
print(open(DATA).read())
print("----- server log -----")
print(open("/tmp/mr-server.log").read())
sys.exit(0 if failed == 0 else 1)
