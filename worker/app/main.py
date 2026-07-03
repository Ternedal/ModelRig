"""ModelRig RAG worker — FastAPI.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8099
The backend proxies /api/v1/rag/* here; clients never call it directly.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import ollama_client as oc
from . import rag
from .store import DocStore

VERSION = "0.6.0"

app = FastAPI(title="ModelRig Worker", version=VERSION)
store = DocStore()


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


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "service": "modelrig-worker",
        "version": VERSION,
        "documents": store.count(),
    }


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
            synthesize=req.synthesize, model=req.model,
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))
