"""Tests for /rag/ingest/image (V10.3) -- the photo->RAG path. The 501 gate
(no vision model configured -> honest refusal, never guess with the gen model)
is the safety property; the happy path must land real chunks in the store."""
import asyncio
import os
import sys
import tempfile

os.environ["MODELRIG_DB"] = tempfile.mktemp(suffix=".db")
os.environ["KALIV_DATA_DIR"] = tempfile.mkdtemp(prefix="kaliv-vision-test-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

passed = failed = 0
def check(cond, msg):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {msg}")
    else: failed += 1; print(f"  FAIL: {msg}")

import app.ollama_client as oc  # noqa: E402
from app import main as M  # noqa: E402
from fastapi import HTTPException  # noqa: E402

def _req(**kw):
    return M.IngestImageReq(image_base64="QUJD", **kw)

def _run(coro):
    try:
        return asyncio.run(coro), None
    except HTTPException as e:
        return None, e

# ---- 501: no vision model configured -> honest refusal ---------------------
os.environ.pop("KALIV_VISION_MODEL", None)
out, err = _run(M.ingest_image(_req()))
check(err is not None and err.status_code == 501,
      "501 when KALIV_VISION_MODEL is unset")
check(err is not None and "KALIV_VISION_MODEL" in err.detail,
      "the 501 names the env var (actionable, not just 'no')")
st = M.rag_image_status()
check(st == {"available": False, "model": None},
      "status: honest 'not available' when unset")

# ---- happy path: extraction -> chunk -> embed -> store ----------------------
seen = {}
async def fake_chat(messages, model=None):
    seen["model"] = model
    seen["images"] = messages[-1].get("images")
    seen["prompt"] = messages[-1]["content"]
    return "KVITTERING\nBrugsen 12/7-2026\nMælk 12,50 kr\nÆg 24,00 kr"
async def fake_embed(text, model=None):
    return [0.1, 0.2, 0.3]
orig_chat, orig_embed = oc.chat, oc.embed
oc.chat, oc.embed = fake_chat, fake_embed
try:
    os.environ["KALIV_VISION_MODEL"] = "llama3.2-vision:11b "  # trailing space on purpose
    st = M.rag_image_status()
    check(st["available"] and st["model"] == "llama3.2-vision:11b",
          "status: available, and the env value is TRIMMED (our footgun rule)")
    out, err = _run(M.ingest_image(_req(source="kvittering-juli")))
    check(err is None and out["chunks_added"] >= 1,
          f"happy path: chunks landed in the index (got {out})")
    check(out is not None and out["source"] == "kvittering-juli",
          "the given source name is used")
    check(seen.get("model") == "llama3.2-vision:11b",
          "the TRIMMED vision model is what gets called")
    check(seen.get("images") == ["QUJD"],
          "the image rides on the user message (Ollama's vision shape)")
    check("ordret" in (seen.get("prompt") or ""),
          "the extraction prompt asks for faithful transcription")
    srcs = [s0["source"] if isinstance(s0, dict) else s0 for s0 in M.store.sources()]
    check(any("kvittering-juli" in str(s0) for s0 in srcs),
          "the source is visible in the store afterwards")

    # ---- 422: the model saw nothing readable --------------------------------
    async def fake_chat_empty(messages, model=None):
        return "   \n  "
    oc.chat = fake_chat_empty
    out, err = _run(M.ingest_image(_req()))
    check(err is not None and err.status_code == 422,
          "422 when extraction is empty -- say so, index nothing")

    # ---- 502: Ollama unreachable --------------------------------------------
    async def fake_chat_down(messages, model=None):
        raise oc.OllamaError("cannot reach Ollama")
    oc.chat = fake_chat_down
    out, err = _run(M.ingest_image(_req()))
    check(err is not None and err.status_code == 502,
          "502 when Ollama errors during extraction")
finally:
    oc.chat, oc.embed = orig_chat, orig_embed
    os.environ.pop("KALIV_VISION_MODEL", None)

print(f"\n===== VISION: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
