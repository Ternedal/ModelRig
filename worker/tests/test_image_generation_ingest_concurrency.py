"""Concurrent requests cannot ingest one image job at the same time."""
import asyncio

import httpx
from fastapi import FastAPI

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJob, ImageJobManager, JobStatus


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()
        self.adapter = object()


def test_concurrent_ingest_returns_conflict(tmp_path, monkeypatch):
    async def scenario():
        service = FakeService()
        service.manager._jobs["job"] = ImageJob(
            id="job", owner_id="alice", status=JobStatus.SUCCEEDED,
            result="00000000-0000-4000-8000-000000000000"
        )
        entered = asyncio.Event()
        release = asyncio.Event()
        count = 0

        async def slow_ingest(owner, job_id, **kwargs):
            nonlocal count
            count += 1
            entered.set()
            await release.wait()
            return "00000000-0000-4000-8000-000000000001"

        monkeypatch.setattr("app.image_generation.api.ingest_completed_job", slow_ingest)
        app = FastAPI()
        app.include_router(build_image_router(
            service, authenticated_owner=lambda: "alice",
            artifact_store=ImageArtifactStore(tmp_path)
        ))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/experimental/images/jobs/job/ingest"
            first = asyncio.create_task(client.post(path))
            await asyncio.wait_for(entered.wait(), 2)
            second = await client.post(path)
            assert second.status_code == 409
            release.set()
            result = await asyncio.wait_for(first, 2)
            assert result.status_code == 200
            assert count == 1

    asyncio.run(scenario())
