"""RAG-to-cloud privacy guard (D4, 2026-07-13).

Invariant: retrieved RAG chunks are the content of your own documents. They must
not reach a cloud model without explicit consent -- per request (allow_rag_cloud)
or operator opt-in (KALIV_ALLOW_RAG_CLOUD). Default is secure: no consent -> the
rig refuses to answer a RAG-grounded question with a cloud model.

Retrieval is mocked so the test needs no Ollama/embeddings: we only care about
what the guard does once documents have matched.

Run: PYTHONPATH=worker python3 tests/worker_rag_cloud.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# The gate must be enabled to reach the RAG branch of /tools/chat, and the guard
# must start from the default-secure state (no global opt-in). KALIV_WORKER_ALLOW_LAN
# lets TestClient's non-loopback requests past the worker's loopback-only
# middleware (1.58.1) so they reach the handler we're testing.
os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)
_tmp = tempfile.mkdtemp(prefix="kaliv-ragcloud-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402


# Pretend a document matched, without needing an embedder.
async def _fake_query(*a, **k):
    return {"matches": [
        {"source": "hemmeligt.txt", "id": 1, "text": "privat dokumentindhold", "score": 0.9},
    ]}


main.rag.query = _fake_query
client = TestClient(main.app)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def chat(body):
    base = {"message": "hvad står der i dokumentet?", "rag": True, "model": "kimi-k2.6"}
    return client.post("/tools/chat", json={**base, **body})


# 1. RAG + cloud + NO consent -> 403, and it's the privacy refusal (not "disabled").
r = chat({"cloud_base_url": "http://127.0.0.1:9/v1", "cloud_key": "k"})
detail = (r.json().get("detail") or "").lower()
check(r.status_code == 403 and "cloud" in detail and "disabled" not in detail,
      f"RAG matched + cloud + no consent -> 403 privacy refusal (got {r.status_code}: {detail[:60]!r})")

# 2. RAG + cloud + per-request consent -> PAST the guard (then fails on the dead
#    cloud URL with 502, which proves the guard let it through).
r = chat({"cloud_base_url": "http://127.0.0.1:9/v1", "cloud_key": "k", "allow_rag_cloud": True})
check(r.status_code != 403, f"RAG + cloud + consent -> past guard (got {r.status_code})")

# 3. RAG + LOCAL model (no cloud_key) -> guard does not apply (local never leaves
#    the rig); fails only because the sandbox has no Ollama.
r = chat({})
check(r.status_code != 403, f"RAG + local model -> past guard (got {r.status_code})")

# 4/5. Operator opt-in via env, and default-secure, tested through the helper.
class _Req:
    allow_rag_cloud = False


os.environ["KALIV_ALLOW_RAG_CLOUD"] = "1"
check(main._rag_cloud_allowed(_Req()) is True, "KALIV_ALLOW_RAG_CLOUD=1 -> allowed")
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)
check(main._rag_cloud_allowed(_Req()) is False, "no consent + no env -> not allowed (default secure)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
