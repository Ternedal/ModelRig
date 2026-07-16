"""Thin async client for the local Ollama HTTP API.

Only the two calls the RAG worker needs: embeddings and non-streaming chat.
All failures are surfaced as OllamaError so the API layer can return 502 instead
of leaking a stack trace.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

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

# Keep the model resident in VRAM between turns. Without this, Ollama unloads
# it after each idle window, so every turn -- especially the non-streaming
# tools path, which cannot show a token until generation finishes -- pays the
# full cold reload (~5 GB into a 3060). On Anders' rig this surfaced as a 25s
# /health and back-to-back tool turns timing out even at a 5 min client
# timeout. "30m" holds it for half an hour idle; "-1" pins it, "0" unloads.
KEEP_ALIVE = os.getenv("MODELRIG_OLLAMA_KEEP_ALIVE", "30m")


class OllamaError(RuntimeError):
    """Any failure talking to Ollama (unreachable, non-200, malformed body)."""


async def embed(text: str, model: str | None = None) -> list[float]:
    model = model or EMBED_MODEL
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{OLLAMA_URL}/api/embeddings",
                             json={"model": model, "prompt": text, "keep_alive": KEEP_ALIVE})
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
                             json={"model": model, "messages": messages, "stream": False, "keep_alive": KEEP_ALIVE})
    except httpx.HTTPError as e:
        raise OllamaError(f"cannot reach Ollama at {OLLAMA_URL}: {e}") from e
    if r.status_code != 200:
        raise OllamaError(f"chat failed ({r.status_code}): {r.text[:200]}")
    return r.json().get("message", {}).get("content", "")


def _validate_cloud_url(base_url: str) -> None:
    """SSRF guard for the client-supplied cloud upstream.

    A client passes cloud_base_url and the worker makes a server-side request to
    it. Reject non-http(s) schemes and any host that resolves to a
    loopback/private/link-local/reserved address, so a caller cannot turn the
    worker into a proxy for internal services (127.0.0.1, 169.254.169.254,
    10/172.16/192.168, ...). Public cloud hosts (Ollama Cloud) are unaffected.

    Set KALIV_CLOUD_ALLOW_PRIVATE=1 to bypass -- e.g. a trusted Ollama upstream
    on your own LAN. NOTE: the check resolves the host at validation time; it is
    not a defence against DNS-rebinding between here and httpx's own connect.
    That residual is accepted for a single-user, token-gated platform.
    """
    if os.getenv("KALIV_CLOUD_ALLOW_PRIVATE", "0") == "1":
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise OllamaError(f"cloud url scheme not allowed: {parsed.scheme or '(none)'!r}")
    host = parsed.hostname
    if not host:
        raise OllamaError("cloud url has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise OllamaError(f"cloud host does not resolve: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise OllamaError(
                f"cloud host {host} resolves to a non-public address ({ip}); "
                "refused to prevent SSRF (set KALIV_CLOUD_ALLOW_PRIVATE=1 to allow)")


async def chat_tools(messages: list[dict], tools: list[dict],
                     model: str | None = None, base_url: str | None = None,
                     api_key: str | None = None) -> dict:
    """One non-streaming chat turn that MAY return tool calls.

    Returns Ollama's message dict: {"content": str, "tool_calls": [...]} .

    A cloud model MAY propose tools (Anders' revision 2026-07-10, superseding
    the earlier "local only" rule) -- but proposing is not executing. WRITES
    are gated: they park server-side and require the confirmation card,
    regardless of origin. READS are NOT gated (the gate checks risk=="write"
    only) -- so a cloud-originated read runs without a card and its result
    travels back to the cloud model: the tool output leaves the house. That is
    a documented OPEN privacy point (SECURITY.md, decision #6 / egress
    classification); do not assume a read-consent gate exists because of an
    old version of this comment. See tools.ToolGate.propose(origin=...).

    Pass tools=[] to guarantee the model cannot request a tool -- that is how
    the follow-up turn after a tool result is made chain-free.
    """
    model = model or GEN_MODEL
    if base_url:
        _validate_cloud_url(base_url)
    # keep_alive is a local-VRAM directive; don't send it to a cloud upstream
    # (same fix as chat_stream -- it can hang the cloud request).
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if not base_url:
        payload["keep_alive"] = KEEP_ALIVE
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
    if base_url:
        _validate_cloud_url(base_url)
    url = (base_url or OLLAMA_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # keep_alive tells a LOCAL Ollama how long to keep the model in VRAM. Ollama
    # Cloud doesn't manage your VRAM, and sending it to the cloud upstream is what
    # made voice-via-cloud hang (regular cloud chat works precisely because the
    # app's CloudClient never sends keep_alive). So only send it to the local rig.
    payload: dict = {"model": model, "messages": messages, "stream": True}
    if not base_url:
        payload["keep_alive"] = KEEP_ALIVE
    client = httpx.AsyncClient(timeout=TIMEOUT)
    try:
        async with client.stream("POST", f"{url}/api/chat", headers=headers,
                                 json=payload) as r:
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
