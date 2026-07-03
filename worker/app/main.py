"""ModelRig RAG worker — FastAPI.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8099
The backend proxies /api/v1/rag/* here; clients never call it directly.
"""
from __future__ import annotations

import logging as pylog
import sys
import time as pytime
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import ollama_client as oc
from . import rag
from .store import DocStore

VERSION = "0.9.0"

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
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))


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
