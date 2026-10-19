"""Owner-scoped ingestion endpoint contract."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJob, ImageJobManager, JobStatus


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()
        self.adapter = object()


def test_ingest_requires_completed_owner_job(tmp_path, monkeypatch):
    service = FakeService()
    job = ImageJob(id="job-1", owner_id="alice", status=JobStatus.SUCCEEDED,
                   result="00000000-0000-4000-8000-000000000000")
    service.manager._jobs[job.id] = job
    store = ImageArtifactStore(tmp_path)
    calls = []

    async def fake_ingest(owner, job_id, **kwargs):
        calls.append((owner, job_id))
        return "00000000-0000-4000-8000-000000000001"

    monkeypatch.setattr("app.image_generation.api.ingest_completed_job", fake_ingest)
    app = FastAPI()

    def identity():
        return "alice"

    app.include_router(build_image_router(
        service, authenticated_owner=identity, artifact_store=store
    ))
    client = TestClient(app)
    path = "/experimental/images/jobs/job-1/ingest"
    app.dependency_overrides[identity] = lambda: "bob"
    assert client.post(path).status_code == 404
    assert not calls
    app.dependency_overrides[identity] = lambda: "alice"
    assert client.post(path).json()["artifact_id"].endswith("0001")
    assert calls == [("alice", "job-1")]
    job.status = JobStatus.RUNNING
    assert client.post(path).status_code == 409
    assert len(calls) == 1
