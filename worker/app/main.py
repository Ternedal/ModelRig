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

VERSION = "1.8.2"

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


@app.get("/rag/ingest/pdf/status")
def rag_pdf_status() -> dict:
    """Whether PDF ingest is available (PyMuPDF installed)."""
    from . import rag_pdf
    return {"available": rag_pdf.is_available()}


class IngestPdfReq(BaseModel):
    # base64-encoded PDF bytes uploaded from a client. Extraction happens here
    # on the worker (PyMuPDF), then the text goes through the same chunk/embed/
    # store pipeline as /rag/ingest -- clients can't extract PDF text easily.
    pdf_base64: str
    source: str | None = None
    chunk_size: int = Field(default=800, ge=100, le=4000)
    overlap: int = Field(default=150, ge=0, le=1000)


@app.post("/rag/ingest/pdf")
async def ingest_pdf(req: IngestPdfReq) -> dict:
    """Extract text from an uploaded PDF and ingest it into the RAG index.
    Returns {source, pages, chars, chunks_added, total}. Clean errors: 501 if
    PyMuPDF isn't installed, 400 for bad base64 / unreadable / encrypted PDF,
    422 if the PDF has no extractable text (e.g. a scan with no OCR layer)."""
    from . import rag_pdf
    import base64
    if not rag_pdf.is_available():
        raise HTTPException(
            status_code=501,
            detail="PDF ingest is not enabled on this rig. Install it with: pip install pymupdf",
        )
    try:
        raw = base64.b64decode(req.pdf_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="pdf_base64 is not valid base64")
    try:
        extracted = rag_pdf.extract_text(raw)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not extracted["text"]:
        # No selectable text -- almost always a scanned PDF with no OCR layer.
        raise HTTPException(
            status_code=422,
            detail="no extractable text in PDF (is it a scan? OCR isn't supported yet)",
        )
    try:
        chunks = await rag.ingest(
            store,
            [{"text": extracted["text"], "source": req.source}],
            chunk_size=req.chunk_size, overlap=req.overlap,
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "source": req.source,
        "pages": extracted["pages"],
        "chars": extracted["chars"],
        "chunks_added": chunks,
        "total": store.count(),
    }


@app.get("/rag/ingest/docx/status")
def rag_docx_status() -> dict:
    """Whether DOCX ingest is available (python-docx installed)."""
    from . import rag_docx
    return {"available": rag_docx.is_available()}


class IngestDocxReq(BaseModel):
    # base64-encoded .docx bytes. Extraction happens on the worker
    # (python-docx), then the text goes through the same pipeline as
    # /rag/ingest. Mirrors /rag/ingest/pdf.
    docx_base64: str
    source: str | None = None
    chunk_size: int = Field(default=800, ge=100, le=4000)
    overlap: int = Field(default=150, ge=0, le=1000)


@app.post("/rag/ingest/docx")
async def ingest_docx(req: IngestDocxReq) -> dict:
    """Extract text from an uploaded .docx and ingest it into the RAG index.
    Returns {source, paragraphs, chars, chunks_added, total}. Clean errors: 501
    if python-docx isn't installed, 400 for bad base64 / unreadable / legacy
    .doc, 422 if there's no extractable text."""
    from . import rag_docx
    import base64
    if not rag_docx.is_available():
        raise HTTPException(
            status_code=501,
            detail="DOCX ingest is not enabled on this rig. Install it with: pip install python-docx",
        )
    try:
        raw = base64.b64decode(req.docx_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="docx_base64 is not valid base64")
    try:
        extracted = rag_docx.extract_text(raw)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not extracted["text"]:
        raise HTTPException(status_code=422, detail="no extractable text in DOCX")
    try:
        chunks = await rag.ingest(
            store,
            [{"text": extracted["text"], "source": req.source}],
            chunk_size=req.chunk_size, overlap=req.overlap,
        )
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "source": req.source,
        "paragraphs": extracted["paragraphs"],
        "chars": extracted["chars"],
        "chunks_added": chunks,
        "total": store.count(),
    }


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


# ---- Alva Voice: ASR (optional) --------------------------------------------
# Phase 1 of Alva Voice. Optional: faster-whisper is NOT a hard worker
# dependency. If it's not installed, this returns 501 with instructions and the
# rest of the worker is unaffected. See app/voice_asr.py and
# ALVA_VOICE_ROADMAP_DELTA.md. NOT YET HARDWARE-TESTED.

@app.get("/voice/asr/status")
def voice_asr_status() -> dict:
    """Whether ASR is available (faster-whisper installed) + configured model."""
    from . import voice_asr
    return {
        "available": voice_asr.is_available(),
        "model": voice_asr._model_name(),
        "device": voice_asr._device(),
        "compute_type": voice_asr._compute_type(),
    }


class AsrReq(BaseModel):
    # Path to a 16 kHz mono audio file readable by the worker. File-based for
    # the MVP (push-to-talk records a file, then transcribes); real-time
    # streaming is a later phase.
    path: str
    language: str = "da"


@app.post("/voice/asr/transcribe")
def voice_asr_transcribe(req: AsrReq) -> dict:
    from . import voice_asr
    if not voice_asr.is_available():
        # 501 Not Implemented: the feature exists but its optional backend isn't
        # installed here. Clear, actionable message rather than a 500 stack.
        raise HTTPException(
            status_code=501,
            detail="Alva Voice ASR is not enabled on this rig. Install it with: "
                   "pip install faster-whisper",
        )
    import os as _os
    if not _os.path.exists(req.path):
        raise HTTPException(status_code=400, detail=f"audio file not found: {req.path}")
    try:
        return voice_asr.transcribe_wav(req.path, language=req.language)
    except RuntimeError as e:
        # Model load / device errors -> 501 with the module's actionable message.
        raise HTTPException(status_code=501, detail=str(e))


# ---- Alva Voice: TTS (optional) --------------------------------------------
# Phase 2 of Alva Voice. Same optional pattern as ASR: piper-tts is NOT a hard
# dependency; absent -> 501 with instructions, worker otherwise unaffected. See
# app/voice_tts.py. NOT YET HARDWARE-TESTED. Piper is GPL-3.0 (fine for private
# use; flagged for redistribution).

@app.get("/voice/tts/status")
def voice_tts_status() -> dict:
    """Whether TTS is available (piper-tts installed) + configured voice."""
    from . import voice_tts
    return {
        "available": voice_tts.is_available(),
        "voice": voice_tts._voice_name(),
        "voices_dir": voice_tts._voices_dir(),
    }


class TtsReq(BaseModel):
    text: str
    # Where to write the synthesized WAV on the rig. The Android layer fetches
    # or streams it; file-based for the MVP.
    out_path: str = "/tmp/alva_tts_out.wav"


@app.post("/voice/tts/synthesize")
def voice_tts_synthesize(req: TtsReq) -> dict:
    from . import voice_tts
    if not voice_tts.is_available():
        raise HTTPException(
            status_code=501,
            detail="Alva Voice TTS is not enabled on this rig. Install it with: "
                   "pip install piper-tts",
        )
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    try:
        return voice_tts.synthesize_to_wav(req.text, req.out_path)
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))


# ---- Alva Voice: full pipeline (ASR -> LLM -> TTS) --------------------------
# Phase 3 (V-MVP.3). Orchestrates one spoken turn and reports time-to-first-
# audio. Needs BOTH ASR and TTS backends installed; 501 with the specific
# missing one otherwise. See app/voice_pipeline.py. NOT YET HARDWARE-TESTED.

class ConverseReq(BaseModel):
    # Path to a 16 kHz mono audio file on the rig (the recorded utterance).
    path: str
    language: str = "da"
    model: str | None = None
    out_dir: str = "/tmp/alva_voice"


@app.post("/voice/converse")
async def voice_converse(req: ConverseReq) -> dict:
    from . import voice_pipeline
    import os as _os
    if not _os.path.exists(req.path):
        raise HTTPException(status_code=400, detail=f"audio file not found: {req.path}")
    try:
        return await voice_pipeline.converse(
            req.path, language=req.language, model=req.model, out_dir=req.out_dir,
        )
    except RuntimeError as e:
        # A missing Voice backend (ASR/TTS not installed) -> 501 with the
        # specific actionable message from the pipeline.
        raise HTTPException(status_code=501, detail=str(e))
    except oc.OllamaError as e:
        # LLM unreachable / model not pulled -> 502 (upstream dependency).
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")


class ConverseUploadReq(BaseModel):
    # base64-encoded audio bytes (16 kHz mono WAV) uploaded from the phone.
    # The existing /voice/converse takes a rig file path, useless over the
    # network -- this variant is what the Android app calls. Mirrors the vision
    # base64 pattern the app already uses.
    audio_base64: str
    language: str = "da"
    model: str | None = None


@app.post("/voice/converse/upload")
async def voice_converse_upload(req: ConverseUploadReq) -> dict:
    """Phone-facing voice turn: decode uploaded audio -> run the full pipeline
    -> return transcript + reply text + a single combined reply WAV (base64) for
    easy playback. Same clean errors as /voice/converse."""
    from . import voice_pipeline
    import base64, tempfile, os as _os, wave, glob
    try:
        raw = base64.b64decode(req.audio_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="audio_base64 is not valid base64")
    tmp_dir = tempfile.mkdtemp(prefix="alva_voice_up_")
    in_path = _os.path.join(tmp_dir, "input.wav")
    with open(in_path, "wb") as f:
        f.write(raw)
    try:
        result = await voice_pipeline.converse(
            in_path, language=req.language, model=req.model, out_dir=tmp_dir,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except oc.OllamaError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    # Concatenate the per-sentence reply WAVs into one WAV for simple playback.
    # Piper uses one voice, so all chunks share format -> we can splice frames.
    chunk_paths = [c["wav"] for c in result.get("chunks", [])]
    audio_b64 = ""
    if chunk_paths:
        combined = _os.path.join(tmp_dir, "reply_combined.wav")
        params = None
        frames = b""
        for p in chunk_paths:
            with wave.open(p, "rb") as wf:
                if params is None:
                    params = wf.getparams()
                frames += wf.readframes(wf.getnframes())
        if params is not None:
            with wave.open(combined, "wb") as out:
                out.setparams(params)
                out.writeframes(frames)
            import base64 as _b64
            with open(combined, "rb") as f:
                audio_b64 = _b64.b64encode(f.read()).decode()
    # Drop the on-disk chunk paths from the response (they're temp + phone-
    # irrelevant); return the combined audio instead.
    result.pop("chunks", None)
    result["audio_base64"] = audio_b64
    return result
