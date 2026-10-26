"""Repeat ingestion of one completed job reuses its existing artifact."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJob, ImageJobManager, JobStatus


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()
        self.adapter = object()


def test_repeat_ingestion_returns_same_artifact(tmp_path, monkeypatch):
    service = FakeService()
    service.manager._jobs["job"] = ImageJob(
        id="job", owner_id="alice", status=JobStatus.SUCCEEDED,
        result="00000000-0000-4000-8000-000000000000"
    )
    calls = []

    async def fake_ingest(owner, job_id, **kwargs):
        calls.append(job_id)
        return "00000000-0000-4000-8000-000000000001"

    monkeypatch.setattr("app.image_generation.api.ingest_completed_job", fake_ingest)
    app = FastAPI()
    app.include_router(build_image_router(
        service, authenticated_owner=lambda: "alice",
        artifact_store=ImageArtifactStore(tmp_path)
    ))
    client = TestClient(app)
    path = "/experimental/images/jobs/job/ingest"
    first = client.post(path)
    second = client.post(path)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == ["job"]
