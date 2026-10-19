"""Concurrent ingestion attempts must not duplicate the same image job."""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJob, ImageJobManager, JobStatus


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()
        self.adapter = object()


def test_ingest_success_path_returns_artifact_id(tmp_path, monkeypatch):
    service = FakeService()
    service.manager._jobs["job"] = ImageJob(
        id="job", owner_id="alice", status=JobStatus.SUCCEEDED,
        result="00000000-0000-4000-8000-000000000000"
    )

    async def fake_ingest(owner, job_id, **kwargs):
        assert (owner, job_id) == ("alice", "job")
        return "00000000-0000-4000-8000-000000000001"

    monkeypatch.setattr("app.image_generation.api.ingest_completed_job", fake_ingest)
    app = FastAPI()
    app.include_router(build_image_router(
        service, authenticated_owner=lambda: "alice",
        artifact_store=ImageArtifactStore(tmp_path)
    ))
    response = TestClient(app).post("/experimental/images/jobs/job/ingest")
    assert response.status_code == 200
    assert response.json() == {"artifact_id": "00000000-0000-4000-8000-000000000001"}
