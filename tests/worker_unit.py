#!/usr/bin/env python3
import os, tempfile

# isolated db + point Ollama at a dead port so upstream calls fail fast
os.environ["MODELRIG_DB"] = tempfile.mktemp(suffix=".db")
os.environ["MODELRIG_OLLAMA_URL"] = "http://127.0.0.1:9"   # nothing listening
os.environ["MODELRIG_OLLAMA_TIMEOUT"] = "3"

from fastapi.testclient import TestClient
from app.main import app
from app.rag import cosine

passed = failed = 0
def check(cond, name):
    global passed, failed
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    passed += cond; failed += (not cond)

# 1. cosine pure-function sanity
check(abs(cosine([1,0,0],[1,0,0]) - 1.0) < 1e-9, "cosine identical -> 1.0")
check(abs(cosine([1,0],[0,1]) - 0.0) < 1e-9, "cosine orthogonal -> 0.0")
check(cosine([1,2],[1,2,3]) == 0.0, "cosine mismatched dims -> 0.0")
check(cosine([], [1]) == 0.0, "cosine empty -> 0.0")

client = TestClient(app)

# 2. health
r = client.get("/healthz")
check(r.status_code == 200 and r.json()["service"] == "modelrig-worker", "GET /healthz -> 200")
print("    ", r.json())

# 3. validation (missing 'query')
r = client.post("/rag/query", json={})
check(r.status_code == 422, "POST /rag/query missing query -> 422 (validation)")

# 4. top_k bounds
r = client.post("/rag/query", json={"query": "x", "top_k": 999})
check(r.status_code == 422, "POST /rag/query top_k>20 -> 422")

# 5. Ollama down -> clean 502 (not a crash)
r = client.post("/rag/query", json={"query": "what is modelrig?"})
check(r.status_code == 502, "POST /rag/query, ollama down -> 502")
print("    detail:", r.json().get("detail", "")[:80])

r = client.post("/rag/ingest", json={"documents": [{"text": "hello", "source": "t"}]})
check(r.status_code == 502, "POST /rag/ingest, ollama down -> 502")

print(f"\n===== WORKER: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
