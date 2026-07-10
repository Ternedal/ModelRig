"""Thin async client for the local Ollama HTTP API.

Only the two calls the RAG worker needs: embeddings and non-streaming chat.
All failures are surfaced as OllamaError so the API layer can return 502 instead
of leaking a stack trace.
"""
from __future__ import annotations

import os

import httpx

OLLAMA_URL = os.getenv("MODELRIG_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("MODELRIG_EMBED_MODEL", "nomic-embed-text")
GEN_MODEL = os.getenv("MODELRIG_GEN_MODEL", "qwen2.5-coder:7b")
# Timeout for calls to Ollama. The default must accommodate a COLD model: a
# first voice turn (or first chat) makes Ollama load e.g. hermes3:8b (~4.7 GB)
# into VRAM before generating a single token, which alone can exceed 60s.
# Verified on Anders' rig 2026-07-09: a too-short timeout anywhere in the chain
# (Android -> Go server -> worker -> Ollama) surfaces on the phone as
# "Software caused connection abort". The shortest timeout wins, so all three
# layers had to be raised.
TIMEOUT = float(os.getenv("MODELRIG_OLLAMA_TIMEOUT", "600"))


class OllamaError(RuntimeError):
    """Any failure talking to Ollama (unreachable, non-200, malformed body)."""


async def embed(text: str, model: str | None = None) -> list[float]:
    model = model or EMBED_MODEL
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{OLLAMA_URL}/api/embeddings",
                             json={"model": model, "prompt": text})
    except httpx.HTTPError as e:
        raise OllamaError(f"cannot reach Ollama at {OLLAMA_URL}: {e}") from e
    if r.status_code != 200:
        raise OllamaError(f"embeddings failed ({r.status_code}): {r.text[:200]}")
    emb = r.json().get("embedding")
    if not emb:
        raise OllamaError("embeddings response missing 'embedding' "
                          f"(is model '{model}' pulled?)")
    return emb


async def chat(messages: list[dict], model: str | None = None) -> str:
    model = model or GEN_MODEL
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{OLLAMA_URL}/api/chat",
                             json={"model": model, "messages": messages, "stream": False})
    except httpx.HTTPError as e:
        raise OllamaError(f"cannot reach Ollama at {OLLAMA_URL}: {e}") from e
    if r.status_code != 200:
        raise OllamaError(f"chat failed ({r.status_code}): {r.text[:200]}")
    return r.json().get("message", {}).get("content", "")


async def chat_tools(messages: list[dict], tools: list[dict],
                     model: str | None = None, base_url: str | None = None,
                     api_key: str | None = None) -> dict:
    """One non-streaming chat turn that MAY return tool calls.

    Returns Ollama's message dict: {"content": str, "tool_calls": [...]} .

    A cloud model MAY propose tools (Anders' revision 2026-07-10, superseding
    the earlier "local only" rule) -- but proposing is not executing. Every
    cloud-originated call goes through the confirmation card, including READ
    tools, because a read result must travel back to the cloud model to be
    phrased: the tool output leaves the house. The gate enforces that, not
    this function; see tools.ToolGate.propose(origin=...).

    Pass tools=[] to guarantee the model cannot request a tool -- that is how
    the follow-up turn after a tool result is made chain-free.
    """
    model = model or GEN_MODEL
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    url = (base_url or OLLAMA_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{url}/api/chat", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise OllamaError(f"cannot reach Ollama at {url}: {e}") from e
    if r.status_code != 200:
        raise OllamaError(f"chat failed ({r.status_code}): {r.text[:200]}")
    return r.json().get("message", {}) or {}


async def chat_stream(messages: list[dict], model: str | None = None,
                      base_url: str | None = None, api_key: str | None = None):
    """Async generator yielding raw NDJSON lines (bytes) from Ollama's streaming
    chat. Raises OllamaError (before the first yield) if the request can't start.

    base_url/api_key let a caller stream from a DIFFERENT Ollama upstream than
    the local rig -- specifically Ollama Cloud. Used by the voice pipeline so a
    spoken question can be answered by a large cloud model (e.g. kimi-k2.6)
    while ASR and TTS stay local. When omitted, behaviour is unchanged: the
    local rig's Ollama, no auth.

    The key is never persisted; it arrives per-request from the app and is used
    only for this call.
    """
    model = model or GEN_MODEL
    url = (base_url or OLLAMA_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    client = httpx.AsyncClient(timeout=TIMEOUT)
    try:
        async with client.stream("POST", f"{url}/api/chat", headers=headers,
                                 json={"model": model, "messages": messages, "stream": True}) as r:
            if r.status_code != 200:
                body = await r.aread()
                raise OllamaError(f"chat failed ({r.status_code}): {body[:200]!r}")
            async for line in r.aiter_lines():
                if line:
                    yield (line + "\n").encode()
    except httpx.HTTPError as e:
        raise OllamaError(f"cannot reach Ollama at {url}: {e}") from e
    finally:
        await client.aclose()
