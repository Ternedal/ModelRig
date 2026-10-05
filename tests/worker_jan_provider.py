#!/usr/bin/env python3
"""Provider-contract tests for Jan/OpenAI-compatible worker generation."""

import asyncio
import json
import os
import sys

sys.path.insert(0, "worker")

from app import ollama_client as oc  # noqa: E402


class FakeResponse:
    def __init__(self, body, status_code=200, lines=None):
        self._body = body
        self.status_code = status_code
        self.text = json.dumps(body)
        self._lines = lines or []

    def json(self):
        return self._body

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeClient:
    calls = []

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aclose(self):
        return None

    async def post(self, url, json=None, headers=None):
        self.calls.append(("post", url, json, headers or {}))
        tool_calls = []
        if json and json.get("tools"):
            tool_calls = [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "note_append", "arguments": '{"text":"hej"}'},
            }]
        return FakeResponse({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "jan-hej",
                    "tool_calls": tool_calls,
                },
                "finish_reason": "stop",
            }]
        })

    def stream(self, method, url, headers=None, json=None):
        self.calls.append(("stream", url, json, headers or {}))
        return StreamContext(FakeResponse({}, lines=[
            'data: {"choices":[{"delta":{"role":"assistant","content":"Jan"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":" virker"},"finish_reason":null}]}',
            "data: [DONE]",
        ]))


async def main():
    old_client = oc.httpx.AsyncClient
    old_provider, old_url, old_key = oc.LLM_PROVIDER, oc.LLM_URL, oc.LLM_KEY
    try:
        oc.httpx.AsyncClient = FakeClient
        oc.LLM_PROVIDER = "jan"
        oc.LLM_URL = "http://127.0.0.1:1337/v1"
        oc.LLM_KEY = "jan-secret"
        FakeClient.calls.clear()

        answer = await oc.chat([{"role": "user", "content": "hej"}], model="jan-model")
        assert answer == "jan-hej", answer
        kind, url, payload, headers = FakeClient.calls[-1]
        assert kind == "post"
        assert url == "http://127.0.0.1:1337/v1/chat/completions", url
        assert payload["model"] == "jan-model"
        assert "keep_alive" not in payload
        assert headers["Authorization"] == "Bearer jan-secret"

        message = await oc.chat_tools(
            [{"role": "user", "content": "lav note"}],
            [{"type": "function", "function": {"name": "note_append", "parameters": {"type": "object"}}}],
            model="jan-model",
        )
        assert message["tool_calls"][0]["function"]["name"] == "note_append"
        assert isinstance(message["tool_calls"][0]["function"]["arguments"], str)

        chunks = []
        async for chunk in oc.chat_stream(
            [{"role": "user", "content": "hej"}],
            model="jan-model",
        ):
            chunks.append(json.loads(chunk))
        assert [x["message"]["content"] for x in chunks] == ["Jan", " virker", ""], chunks
        assert chunks[-1]["done"] is True

        # Jan is generation-only in this slice. Embeddings remain deliberately
        # tied to the existing local Ollama endpoint.
        oc.OLLAMA_URL = "http://ollama.test"
        await oc.embed("abc", model="embed-model")
        _, embed_url, embed_payload, _ = FakeClient.calls[-1]
        assert embed_url == "http://ollama.test/api/embed", embed_url
        assert embed_payload["model"] == "embed-model"

        print("PASS: Jan/OpenAI worker provider contract")
    finally:
        oc.httpx.AsyncClient = old_client
        oc.LLM_PROVIDER, oc.LLM_URL, oc.LLM_KEY = old_provider, old_url, old_key


if __name__ == "__main__":
    asyncio.run(main())
