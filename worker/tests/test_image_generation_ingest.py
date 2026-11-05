"""Mocked ComfyUI ingestion test: job ownership -> download -> sanitized store."""
import asyncio
import io
import uuid

import httpx
import pytest

from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.comfyui_adapter import ComfyUIAdapter
from app.image_generation.ingest import ingest_completed_job
from app.image_generation.jobs import ImageJobManager, JobStatus


def test_ingest_completed_job(tmp_path):
    image = pytest.importorskip("PIL.Image")
    source = io.BytesIO()
    image.new("RGB", (12, 12), (100, 40, 20)).save(source, format="PNG")
    png = source.getvalue()
    prompt_id = str(uuid.uuid4())
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json={
                prompt_id: {"outputs": {"9": {"images": [
                    {"filename": "sample.png", "subfolder": "", "type": "output"}
                ]}}}
            })
        if request.url.path == "/view":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png)
        return httpx.Response(404)

    async def run():
        manager = ImageJobManager()
        job = await manager.submit("alice", lambda: asyncio.sleep(0, result=prompt_id))
        await manager._tasks[job.id]
        assert job.status == JobStatus.SUCCEEDED
        async with ComfyUIAdapter(transport=httpx.MockTransport(handler)) as adapter:
            store = ImageArtifactStore(tmp_path)
            with pytest.raises(ValueError):
                await ingest_completed_job("bob", job.id, manager=manager, adapter=adapter, store=store)
            assert requests == []
            artifact_id = await ingest_completed_job(
                "alice", job.id, manager=manager, adapter=adapter, store=store
            )
            result = store.get_png("alice", artifact_id)
            assert result is not None
            with image.open(io.BytesIO(result)) as decoded:
                assert decoded.size == (12, 12)
            assert store.get_png("bob", artifact_id) is None
            await manager.shutdown()

    asyncio.run(run())
