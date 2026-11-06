"""Contract test: RAG ingest embeds chunks in batches, not one HTTP call per chunk.

Measured on the rig (RAG_BENCHMARK.md): 10.000 chunks took >35 min because
ingest sent one /api/embed request per chunk. embed_many() groups chunks into
MODELRIG_EMBED_BATCH-sized requests. This test pins the contract against a fake
Ollama transport: request count, order, fail-closed on short answers, the
legacy fallback, and that ingest actually goes through the batched path.

Run: PYTHONPATH=worker python3 tests/worker_rag_embed_batch.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

import httpx  # noqa: E402

from app import ollama_client as oc  # noqa: E402
from app import rag  # noqa: E402
from app.store import DocStore  # noqa: E402

passed = failed = 0


def check(message: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def _vec(text: str) -> list[float]:
    v = [0.0] * 26
    for ch in text.lower():
        i = ord(ch) - 97
        if 0 <= i < 26:
            v[i] += 1.0
    return v


class FakeOllama:
    """Records every request; answers /api/embed (batch) and /api/embeddings (legacy)."""

    def __init__(self, *, batch_route: bool = True, short_by: int = 0):
        self.requests: list[tuple[str, dict]] = []
        self.batch_route = batch_route
        self.short_by = short_by

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        self.requests.append((request.url.path, payload))
        if request.url.path == "/api/embed":
            if not self.batch_route:
                return httpx.Response(404)
            inputs = payload["input"]
            if isinstance(inputs, str):
                inputs = [inputs]
            rows = [_vec(t) for t in inputs][: max(0, len(inputs) - self.short_by)]
            return httpx.Response(200, json={"embeddings": rows})
        if request.url.path == "/api/embeddings":
            return httpx.Response(200, json={"embedding": _vec(payload["prompt"])})
        return httpx.Response(404)

    def install(self):
        transport = httpx.MockTransport(self.handler)
        real = httpx.AsyncClient

        def client(*args, **kwargs):
            kwargs["transport"] = transport
            return real(*args, **kwargs)

        oc.httpx.AsyncClient = client
        return real


def _with_fake(fake: FakeOllama, fn):
    real = fake.install()
    try:
        return fn()
    finally:
        oc.httpx.AsyncClient = real


texts = [f"chunk {i} " + "abc"[i % 3] * 5 for i in range(70)]

# 1 -- batching: 70 texts at batch 32 -> 3 requests, vectors in input order
fake = FakeOllama()
got = _with_fake(fake, lambda: asyncio.run(oc.embed_many(texts, batch_size=32)))
check("70 chunks go out as 3 batched /api/embed requests, not 70",
      [p for p, _ in fake.requests] == ["/api/embed"] * 3)
check("batch sizes are 32, 32, 6", [len(p["input"]) for _, p in fake.requests] == [32, 32, 6])
check("every input is embedded exactly once, in order", got == [_vec(t) for t in texts])
check("the batch request carries the model and keep_alive",
      all(p["model"] == oc.EMBED_MODEL and p["keep_alive"] == oc.KEEP_ALIVE for _, p in fake.requests))

# 2 -- default batch size comes from EMBED_BATCH (env-tunable), not a hidden constant
fake = FakeOllama()
_with_fake(fake, lambda: asyncio.run(oc.embed_many(texts)))
check("default batch size is oc.EMBED_BATCH",
      max(len(p["input"]) for _, p in fake.requests) == min(oc.EMBED_BATCH, len(texts)))
check("empty input makes no request", asyncio.run(oc.embed_many([])) == [])

# 3 -- fail closed: a response short by one vector is an OllamaError, never a misalignment
fake = FakeOllama(short_by=1)
try:
    _with_fake(fake, lambda: asyncio.run(oc.embed_many(texts[:5])))
    check("a short embeddings answer raises OllamaError", False)
except oc.OllamaError as exc:
    check("a short embeddings answer raises OllamaError", True)
    check("the error names the count mismatch", "4 vectors for 5 inputs" in str(exc))

# 4 -- legacy server (404 on /api/embed): falls back to one legacy call per text, still ordered
fake = FakeOllama(batch_route=False)
got = _with_fake(fake, lambda: asyncio.run(oc.embed_many(texts[:5], batch_size=2)))
legacy = [p for p, _ in fake.requests if p == "/api/embeddings"]
check("without the batch route every text is embedded through the legacy route",
      len(legacy) == 5 and got == [_vec(t) for t in texts[:5]])

# 5 -- ingest goes through the batched path: one request for many chunks, and the
#      corpus holds exactly the batched vectors
fake = FakeOllama()
doc = {"text": " ".join(f"word{i}" for i in range(400)), "source": "batched.txt"}
with tempfile.TemporaryDirectory(prefix="rag-embed-batch-") as td:
    with DocStore(str(Path(td) / "i.db")) as store:
        added, _ = _with_fake(
            fake, lambda: asyncio.run(rag.ingest(store, [doc], chunk_size=120, overlap=20)))
        embed_requests = [p for p, _ in fake.requests if p == "/api/embed"]
        check("ingest embeds all chunks in far fewer requests than chunks",
              added > 5 and len(embed_requests) < added)
        check("ingest stores one row per chunk", store.count() == added)
        check("ingest sends every chunk, each once",
              sum(len(p["input"]) for _, p in fake.requests) == added)

# 6 -- ingest commits nothing when the batch answer is short (atomicity survives batching)
fake = FakeOllama(short_by=1)
with tempfile.TemporaryDirectory(prefix="rag-embed-batch-") as td:
    with DocStore(str(Path(td) / "i.db")) as store:
        try:
            _with_fake(fake, lambda: asyncio.run(rag.ingest(store, [doc], chunk_size=120, overlap=20)))
            check("a short batch answer aborts ingest", False)
        except oc.OllamaError:
            check("a short batch answer aborts ingest", True)
        check("nothing was written after the aborted ingest", store.count() == 0)

# 7 -- the env knob is wired: MODELRIG_EMBED_BATCH is read at import
src = (Path(__file__).resolve().parents[1] / "worker/app/ollama_client.py").read_text()
check("MODELRIG_EMBED_BATCH is the documented knob", 'getenv("MODELRIG_EMBED_BATCH"' in src)
check("EMBED_BATCH is at least 1 even when misconfigured", oc.EMBED_BATCH >= 1)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
