"""ModelRig RAG worker — FastAPI.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8099
The backend proxies /api/v1/rag/* here; clients never call it directly.
"""
from __future__ import annotations

import json
import logging as pylog
import sys
import time as pytime
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import ollama_client as oc
from . import rag
from .store import DocStore

VERSION = "0.20.23"

app = FastAPI(title="ModelRig Worker", version=VERSION)
store = DocStore()

# Structured request logging with a request id that the backend propagates via
# X-Request-ID, so one request can be traced across backend + worker logs.
_logger = pylog.getLogger("modelrig.worker")
if not _logger.handlers:
    _h = pylog.StreamHandler(sys.stdout)
    _h.setFormatter(pylog.Formatter("%(asctime)s %(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(pylog.INFO)
    _logger.propagate = False


@app.middleware("http")
async def request_logger(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    start = pytime.perf_counter()
    response = await call_next(request)
    dur_ms = int((pytime.perf_counter() - start) * 1000)
    response.headers["x-request-id"] = rid
    _logger.info("level=info req=%s method=%s path=%s status=%d dur_ms=%d",
                 rid, request.method, request.url.path, response.status_code, dur_ms)
    return response


class IngestDoc(BaseModel):
    text: str
    source: str | None = None


class IngestReq(BaseModel):
    documents: list[IngestDoc]
    chunk_size: int = Field(default=800, ge=100, le=4000)
    overlap: int = Field(default=150, ge=0, le=1000)


class QueryReq(BaseModel):
    query: str
    top_k: int = Field(default=4, ge=1, le=20)
    synthesize: bool = True
    model: str | None = None
    source: str | None = None
    # Starting default, not empirically tuned against real documents/queries --
    # nomic-embed-text cosine scores for genuinely related content typically
    # sit well above 0.5, unrelated content often around 0.1-0.3. Adjust via
    # this field once real usage data suggests a better cutoff.
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "service": "modelrig-worker",
        "version": VERSION,
        "documents": store.count(),
    }


@app.get("/health/deep")
async def health_deep() -> dict:
    """Actually round-trip an embedding through Ollama, so this proves the model
    responds — not just that the worker process is up. Returns ok + dims/latency,
    or ok=false + error (still HTTP 200; the body carries the verdict)."""
    import time as _t
    start = _t.perf_counter()
    try:
        vec = await oc.embed("ping")
        dur_ms = int((_t.perf_counter() - start) * 1000)
        return {"ok": True, "embed_dims": len(vec), "latency_ms": dur_ms}
    except oc.OllamaError as e:
        dur_ms = int((_t.perf_counter() - start) * 1000)
        return {"ok": False, "error": str(e), "latency_ms": dur_ms}


@app.post("/rag/ingest")
async def ingest(req: IngestReq) -> dict:
    try:
        chunks = await rag.ingest(
            store, [d.model_dump() for d in req.documents],
            chunk_size=req.chunk_size, overlap=req.overlap,
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"documents": len(req.documents), "chunks_added": chunks, "total": store.count()}


@app.post("/rag/query")
async def query(req: QueryReq) -> dict:
    try:
        return await rag.query(
            store, req.query, top_k=req.top_k,
            synthesize=req.synthesize, model=req.model, source=req.source,
            min_score=req.min_score,
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/rag/chat")
async def rag_chat(req: QueryReq):
    """Retrieve context, then STREAM the answer as NDJSON.

    The retrieval (embedding) happens first, so an Ollama failure there returns a
    clean 502. The first streamed line is `{"sources": [...]}` (what context was
    used); the remaining lines are Ollama's chat NDJSON (message.content deltas).
    A chat failure mid-stream is surfaced as a final `{"error": ...}` line.
    """
    try:
        matches = (await rag.query(
            store, req.query, top_k=req.top_k, synthesize=False, source=req.source,
            min_score=req.min_score,
        ))["matches"]
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))

    context = "\n\n".join(f"[{m['source'] or m['id']}] {m['text']}" for m in matches)
    messages = [
        {"role": "system",
         "content": "Answer using ONLY the provided context. "
                    "If the answer is not in the context, say you don't know."},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {req.query}"},
    ]

    async def gen():
        # One chip per SOURCE, not per chunk. Several chunks from the same
        # file share a source name; emitting one head entry each produced
        # duplicate chips client-side (e.g. "test.txt" twice for a 2-chunk
        # file -- seen on-device 6/7 & 7/7-2026). Client .distinct() couldn't
        # collapse them because each entry's chunk_index differed. Dedup here,
        # once, for every client; keep the best (highest) score per source and
        # count how many chunks matched so the UI can show it if it wants.
        best: dict[str, dict] = {}
        for m in matches:
            key = m["source"] or m["id"]
            prev = best.get(key)
            if prev is None or m["score"] > prev["score"]:
                best[key] = {"source": m["source"], "score": m["score"],
                             "chunks": (prev["chunks"] if prev else 0) + 1}
            else:
                prev["chunks"] += 1
        head = {"sources": [
            {"source": v["source"], "score": v["score"], "chunks": v["chunks"]}
            for v in sorted(best.values(), key=lambda x: x["score"], reverse=True)
        ]}
        yield (json.dumps(head) + "\n").encode()
        if not matches:
            # min_score filtered everything -> no grounded context. Emit an
            # explicit don't-know as a chat delta and skip the LLM call
            # entirely (both honest AND one less Ollama round-trip). Shaped
            # like an Ollama message chunk so the client's existing NDJSON
            # parser renders it with no special-casing. Mirrors the
            # non-streaming /rag/query branch so both clients behave the same.
            msg = "Jeg kan ikke finde noget relevant i kilderne til at besvare det. / I don't have relevant context to answer that."
            yield (json.dumps({"message": {"content": msg}, "done": True}) + "\n").encode()
            return
        try:
            async for chunk in oc.chat_stream(messages, model=req.model):
                yield chunk
        except oc.OllamaError as e:
            yield (json.dumps({"error": str(e)}) + "\n").encode()

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/rag/sources")
def sources() -> dict:
    return {"sources": [
        {"source": s, "chunks": n, "last_ingested_at": ts}
        for (s, n, ts) in store.sources()
    ]}


@app.get("/rag/stats")
def stats() -> dict:
    return store.stats()


@app.delete("/rag/source")
def delete_source(source: str) -> dict:
    """Delete all chunks for a source. 404 if the source has no chunks."""
    removed = store.delete_source(source)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"no chunks for source {source!r}")
    return {"source": source, "removed": removed, "total": store.count()}
