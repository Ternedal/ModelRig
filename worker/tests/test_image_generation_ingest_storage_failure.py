"""External storage failures during ingestion must not leak internal errors."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJob, JobStatus


def test_ingest_storage_failure_is_service_unavailable(tmp_path, monkeypatch):
    import app.image_generation.api as api_module
    store = ImageArtifactStore(tmp_path)

    class Manager:
        _jobs = {"job-1": True}
        def get(self, owner, job_id):
            if owner == "alice" and job_id == "job-1":
                return ImageJob(
                    id="job-1", owner_id="alice", status=JobStatus.SUCCEEDED,
                    created_at=0, completed_at=0, result="prompt-id",
                )
            return None

    class Service:
        manager = Manager()
        adapter = object()

    async def missing_storage(*args, **kwargs):
        raise RuntimeError("External media volume unavailable")

    monkeypatch.setattr(api_module, "ingest_completed_job", missing_storage)
    app = FastAPI()
    app.include_router(build_image_router(
        Service(), authenticated_owner=lambda: "alice", artifact_store=store
    ))
    response = TestClient(app).post("/experimental/images/jobs/job-1/ingest")
    assert response.status_code == 503
    assert response.json() == {"detail": "Image ingestion storage unavailable"}
