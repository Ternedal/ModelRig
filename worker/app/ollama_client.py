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
TIMEOUT = float(os.getenv("MODELRIG_OLLAMA_TIMEOUT", "60"))


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
