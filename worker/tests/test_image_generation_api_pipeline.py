"""Opt-in image API integration: submit -> poll -> ingest -> download.

Uses a deterministic fake local engine and a sanitizer stub. A separate
Pillow/ComfyUI campaign must verify real decoding and GPU execution.
"""
import asyncio

import httpx

from fastapi import FastAPI

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.comfyui_adapter import ComfyUIAdapter
from app.image_generation.service import ImageGenerationService
from app.image_generation.workflow import WorkflowSlots


def test_image_api_complete_owner_scoped_flow(tmp_path, monkeypatch):
    async def scenario():
        prompt_id = "00000000-0000-4000-8000-000000000001"
        artifact = b"\x89PNG\r\n\x1a\n" + b"sanitized-fixture"
        submitted = []
        source_png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                      + (1).to_bytes(4, "big") + (1).to_bytes(4, "big"))

        def engine(request):
            if request.url.path == "/prompt":
                submitted.append(request.content)
                return httpx.Response(200, json={"prompt_id": prompt_id})
            if request.url.path == f"/history/{prompt_id}":
                return httpx.Response(200, json={prompt_id: {
                    "outputs": {"save": {"images": [
                        {"filename": "image.png", "subfolder": "", "type": "output"}
                    ]}}
                }})
            if request.url.path == "/view":
                return httpx.Response(200, headers={"content-type": "image/png"},
                                      content=source_png)
            return httpx.Response(404)

        monkeypatch.setattr(
            "app.image_generation.ingest.sanitize_to_png",
            lambda data, **kwargs: artifact if data == source_png else None
        )
        adapter = ComfyUIAdapter(transport=httpx.MockTransport(engine))
        service = ImageGenerationService(
            adapter, {"1": {"class_type": "CLIPTextEncode",
                            "inputs": {"text": "original"}}},
            WorkflowSlots(prompt_node="1"), poll_interval=0.001, max_polls=3
        )
        store = ImageArtifactStore(tmp_path)
        app = FastAPI()

        def identity():
            return "alice"

        app.include_router(build_image_router(
            service, authenticated_owner=identity, artifact_store=store
        ))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/experimental/images/jobs",
                                        json={"prompt": "a lighthouse"})
            assert created.status_code == 202
            job_id = created.json()["id"]
            for _ in range(100):
                state = await client.get(f"/experimental/images/jobs/{job_id}")
                if state.json()["status"] == "succeeded":
                    break
                await asyncio.sleep(0.01)
            assert state.json()["status"] == "succeeded"
            assert submitted
            ingested = await client.post(
                f"/experimental/images/jobs/{job_id}/ingest"
            )
            assert ingested.status_code == 200, ingested.text
            artifact_id = ingested.json()["artifact_id"]
            download = await client.get(
                f"/experimental/images/artifacts/{artifact_id}"
            )
            assert download.status_code == 200
            assert download.content == artifact
            assert (await client.post(
                f"/experimental/images/jobs/{job_id}/ingest"
            )).json()["artifact_id"] == artifact_id
            app.dependency_overrides[identity] = lambda: "bob"
            assert (await client.get(
                f"/experimental/images/artifacts/{artifact_id}"
            )).status_code == 404
            assert (await client.post(
                f"/experimental/images/jobs/{job_id}/ingest"
            )).status_code == 404
        await service.shutdown()
        await adapter.aclose()

    asyncio.run(scenario())
