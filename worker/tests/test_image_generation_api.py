"""The experimental image API is owner-scoped and never mounted by default."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.jobs import ImageJobManager


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()

    async def submit(self, owner, prompt, seed):
        import asyncio
        return await self.manager.submit(owner, lambda: asyncio.sleep(0, result="prompt-id"))


def test_authentication_and_owner_isolation():
    service = FakeService()
    app = FastAPI()

    def identity():
        return "alice"

    app.include_router(build_image_router(service, authenticated_owner=identity))
    client = TestClient(app)
    created = client.post("/experimental/images/jobs", json={"prompt": "a castle"})
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert "result" not in created.json()
    assert client.get(f"/experimental/images/jobs/{job_id}").status_code == 200

    app.dependency_overrides[identity] = lambda: "bob"
    assert client.get(f"/experimental/images/jobs/{job_id}").status_code == 404
    assert client.delete(f"/experimental/images/jobs/{job_id}").status_code == 404
    app.dependency_overrides[identity] = lambda: None
    assert client.get(f"/experimental/images/jobs/{job_id}").status_code == 401


def test_image_api_requires_auth_dependency():
    import pytest
    with pytest.raises(ValueError):
        build_image_router(FakeService(), authenticated_owner=None)


def test_image_api_rejects_malformed_trusted_owner():
    app = FastAPI()
    def identity():
        return "alice"
    app.include_router(build_image_router(FakeService(), authenticated_owner=identity))
    client = TestClient(app)
    for malformed in ("", " alice", "alice ", "alice\nadmin", "alice\x00", "x" * 129):
        app.dependency_overrides[identity] = lambda value=malformed: value
        response = client.post("/experimental/images/jobs", json={"prompt": "test"})
        assert response.status_code == 401
