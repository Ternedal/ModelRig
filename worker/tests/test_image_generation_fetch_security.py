"""Boundary regression: never trust the HTTP content-type alone."""
import asyncio
import httpx
import pytest

from app.image_generation.comfyui_adapter import ComfyUIAdapter, ComfyUIError
from app.image_generation.outputs import ImageDescriptor


def test_spoofed_png_content_type_is_rejected():
    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "image/png"},
                content=b"not really a PNG image" * 4,
            )
        )
        async with ComfyUIAdapter(transport=transport) as adapter:
            with pytest.raises(ComfyUIError, match="header"):
                await adapter.fetch_output(
                    ImageDescriptor("render.png", "", "output")
                )

    asyncio.run(run())


def test_unapproved_descriptor_is_rejected_before_network():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b"unused")

    async def run():
        async with ComfyUIAdapter(transport=httpx.MockTransport(handler)) as adapter:
            with pytest.raises(ValueError):
                await adapter.fetch_output(
                    ImageDescriptor("../secret.png", "", "output")
                )
    asyncio.run(run())
    assert not requests
