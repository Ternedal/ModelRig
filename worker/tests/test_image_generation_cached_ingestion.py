"""Regression: cached ingestion must not hide an unavailable external media volume."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation import api as image_api
from app.image_generation.jobs import ImageJob, JobStatus


def test_cached_ingestion_rechecks_external_storage(monkeypatch):
    job = ImageJob(id="completed-job", owner_id="alice", status=JobStatus.SUCCEEDED)
    manager = SimpleNamespace(_jobs={job.id: job}, get=lambda owner, key: job if owner == "alice" and key == job.id else None)
    service = SimpleNamespace(manager=manager, adapter=object())
    calls = []

    async def fake_ingest(owner, job_id, **kwargs):
        calls.append((owner, job_id))
        return "stored-image"

    class Store:
        available = True

        def get_png(self, owner, artifact_id):
            if not self.available:
                raise RuntimeError("external drive disconnected")
            return b"PNG" if owner == "alice" and artifact_id == "stored-image" else None

    store = Store()
    monkeypatch.setattr(image_api, "ingest_completed_job", fake_ingest)
    app = FastAPI()
    app.include_router(image_api.build_image_router(
        service, authenticated_owner=lambda: "alice", artifact_store=store
    ))
    client = TestClient(app)
    url = "/experimental/images/jobs/completed-job/ingest"

    first = client.post(url)
    assert first.status_code == 200
    assert first.json() == {"artifact_id": "stored-image"}
    assert len(calls) == 1

    cached = client.post(url)
    assert cached.status_code == 200
    assert len(calls) == 1

    store.available = False
    unavailable = client.post(url)
    assert unavailable.status_code == 503
    assert len(calls) == 1
    assert "stored-image" not in unavailable.text


def test_cached_ingestion_recovers_when_file_was_deleted(monkeypatch):
    job = ImageJob(id="completed-job", owner_id="alice", status=JobStatus.SUCCEEDED)
    manager = SimpleNamespace(_jobs={job.id: job}, get=lambda owner, key: job if owner == "alice" and key == job.id else None)
    service = SimpleNamespace(manager=manager, adapter=object())
    stored = set()
    calls = []

    async def fake_ingest(owner, job_id, **kwargs):
        artifact_id = f"image-{len(calls) + 1}"
        calls.append(artifact_id)
        stored.add(artifact_id)
        return artifact_id

    class Store:
        def get_png(self, owner, artifact_id):
            return b"PNG" if owner == "alice" and artifact_id in stored else None

    monkeypatch.setattr(image_api, "ingest_completed_job", fake_ingest)
    app = FastAPI()
    app.include_router(image_api.build_image_router(
        service, authenticated_owner=lambda: "alice", artifact_store=Store()
    ))
    client = TestClient(app)
    url = "/experimental/images/jobs/completed-job/ingest"
    assert client.post(url).json() == {"artifact_id": "image-1"}
    stored.clear()
    recovered = client.post(url)
    assert recovered.status_code == 200
    assert recovered.json() == {"artifact_id": "image-2"}
    assert calls == ["image-1", "image-2"]
