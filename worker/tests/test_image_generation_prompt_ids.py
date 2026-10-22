"""Validate engine prompt IDs at the submission trust boundary."""
import asyncio

import httpx
import pytest

from app.image_generation.comfyui_adapter import ComfyUIAdapter, ComfyUIError


def test_invalid_engine_prompt_id_rejected():
    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"prompt_id": "../unsafe"})
        )
        async with ComfyUIAdapter(transport=transport) as adapter:
            with pytest.raises(ComfyUIError, match="invalid prompt ID"):
                await adapter.submit({"1": {"class_type": "SaveImage"}}, "client")
    asyncio.run(run())


def test_valid_engine_prompt_id_normalized():
    async def run():
        value = "AAAAAAAA-AAAA-4AAA-AAAA-AAAAAAAAAAAA"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"prompt_id": value})
        )
        async with ComfyUIAdapter(transport=transport) as adapter:
            result = await adapter.submit({"1": {"class_type": "SaveImage"}}, "client")
            assert result == value.lower()
    asyncio.run(run())
