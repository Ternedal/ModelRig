"""Contract tests for the unmounted ComfyUI transport adapter."""
import asyncio
import uuid

import httpx
import pytest

from app.image_generation.comfyui_adapter import (
    ComfyUIAdapter,
    ComfyUIError,
)


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8188",
    "http://example.com:8188",
    "http://192.168.1.10:8188",
    "http://127.0.0.1:8188/path",
    "http://user:pass@localhost:8188",
])
def test_rejects_non_loopback_or_unsafe_endpoint(url):
    with pytest.raises(ValueError):
        ComfyUIAdapter(url)


def test_submit_and_history():
    prompt_id = str(uuid.uuid4())
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/prompt":
            assert request.method == "POST"
            assert request.read()
            return httpx.Response(200, json={"prompt_id": prompt_id})
        return httpx.Response(200, json={prompt_id: {"outputs": {}}})

    async def run():
        async with ComfyUIAdapter(
            transport=httpx.MockTransport(handler)
        ) as adapter:
            assert await adapter.submit({"1": {"class_type": "KSampler"}}, "test") == prompt_id
            assert prompt_id in await adapter.history(prompt_id)

    asyncio.run(run())
    assert calls == [("POST", "/prompt"), ("GET", f"/history/{prompt_id}")]


def test_transport_error_is_sanitized():
    async def run():
        async with ComfyUIAdapter(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(503, text="private upstream details")
            )
        ) as adapter:
            with pytest.raises(ComfyUIError, match="Local image engine request failed"):
                await adapter.submit({"1": {}}, "test")

    asyncio.run(run())


def test_rejects_invalid_prompt_id_before_http():
    async def run():
        async with ComfyUIAdapter(
            transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))
        ) as adapter:
            with pytest.raises(ValueError):
                await adapter.history("../../etc/passwd")

    asyncio.run(run())
