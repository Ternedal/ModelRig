#!/usr/bin/env python3
import os, tempfile
os.environ["MODELRIG_DB"] = tempfile.mktemp(suffix=".db")

# Stub embeddings BEFORE any request: 26-dim lowercase letter-count vector so
# cosine is meaningful and the whole pipeline runs without a real Ollama.
import app.ollama_client as oc

def _vec(text: str):
    v = [0.0] * 26
    for ch in text.lower():
        i = ord(ch) - 97
        if 0 <= i < 26:
            v[i] += 1.0
    return v

async def fake_embed(text, model=None):
    return _vec(text)

oc.embed = fake_embed  # rag calls oc.embed at runtime → picks this up

from fastapi.testclient import TestClient
from app.main import app
from app.rag import chunk_text

client = TestClient(app)
passed = failed = 0
def check(cond, name):
    global passed, failed
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    passed += bool(cond); failed += (not cond)

# ---- chunk_text unit tests ----
check(chunk_text("") == [], "chunk empty -> []")
check(chunk_text("short text") == ["short text"], "chunk short -> single chunk")

long = " ".join(f"word{i}" for i in range(400))  # ~2.7k chars
cs = chunk_text(long, chunk_size=800, overlap=150)
check(len(cs) >= 3, f"chunk long -> multiple chunks ({len(cs)})")
check(all(len(c) <= 800 for c in cs), "every chunk within chunk_size")
check(set(long.split()) <= set(" ".join(cs).split()), "chunking loses no words")

# ---- ingest (chunked) via HTTP ----
r = client.post("/rag/ingest", json={"documents": [{"text": long, "source": "big"}],
                                     "chunk_size": 800, "overlap": 150})
check(r.status_code == 200, "ingest -> 200")
body = r.json()
check(body["chunks_added"] == len(cs), f"chunks_added matches chunk_text ({body['chunks_added']} vs {len(cs)})")
check(body["total"] == len(cs), "store total == chunks stored")

# ---- retrieval picks the nearest source ----
client.post("/rag/ingest", json={"documents": [
    {"text": "alpha bravo charlie delta", "source": "A"},
    {"text": "xray yankee zulu omega", "source": "B"}]})
r = client.post("/rag/query", json={"query": "yankee zulu", "top_k": 1, "synthesize": False})
check(r.status_code == 200, "query -> 200")
matches = r.json()["matches"]
check(len(matches) == 1 and matches[0]["source"] == "B",
      f"retrieval returns nearest source (got {matches[0]['source'] if matches else None})")
check("chunk_index" in matches[0] and "score" in matches[0], "match carries chunk_index + score")

# ---- source management: stats / sources / delete ----
# state now: "big" (len(cs) chunks), "A" (1), "B" (1)
r = client.get("/rag/stats")
st = r.json()
check(r.status_code == 200 and st["sources"] == 3, f"stats sources == 3 (got {st.get('sources')})")
check(st["chunks"] == len(cs) + 2, f"stats chunks == {len(cs)+2} (got {st.get('chunks')})")

r = client.get("/rag/sources")
srcs = {s["source"]: s["chunks"] for s in r.json()["sources"]}
check(r.status_code == 200 and set(srcs) == {"big", "A", "B"}, f"sources lists all (got {set(srcs)})")
check(srcs.get("big") == len(cs) and srcs.get("A") == 1, "per-source chunk counts correct")

r = client.delete("/rag/source", params={"source": "A"})
check(r.status_code == 200 and r.json()["removed"] == 1, "delete source A -> removed 1")
check(r.json()["total"] == len(cs) + 1, "total drops after delete")

r = client.get("/rag/stats")
check(r.json()["sources"] == 2, "stats sources == 2 after delete")

r = client.delete("/rag/source", params={"source": "does-not-exist"})
check(r.status_code == 404, "delete unknown source -> 404")

r = client.post("/rag/query", json={"query": "alpha bravo", "top_k": 3, "synthesize": False})
returned_sources = {m["source"] for m in r.json()["matches"]}
check("A" not in returned_sources, "deleted source no longer retrievable")

# ---- query restricted to a single source ----
# remaining state: "big" (many chunks), "B" (1)
r = client.post("/rag/query", json={"query": "xray yankee zulu", "top_k": 5,
                                     "synthesize": False, "source": "B"})
srcs = {m["source"] for m in r.json()["matches"]}
check(srcs == {"B"}, f"source filter returns only that source (got {srcs})")
r = client.post("/rag/query", json={"query": "word5 word6", "top_k": 5,
                                     "synthesize": False, "source": "big"})
srcs = {m["source"] for m in r.json()["matches"]}
check(srcs <= {"big"} and srcs, f"source filter 'big' -> only big (got {srcs})")

print(f"\n===== WORKER V1: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
