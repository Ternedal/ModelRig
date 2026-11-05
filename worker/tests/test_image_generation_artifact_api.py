"""Artifact downloads are opt-in, private and non-cacheable."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.jobs import ImageJobManager


class FakeService:
    def __init__(self):
        self.manager = ImageJobManager()


def test_artifact_download_scoped_to_owner(tmp_path):
    store = ImageArtifactStore(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"trusted-sanitized-fixture"
    artifact_id = store.put_png("alice", payload)
    app = FastAPI()

    def identity():
        return "alice"

    app.include_router(build_image_router(
        FakeService(), authenticated_owner=identity, artifact_store=store
    ))
    client = TestClient(app)
    path = f"/experimental/images/artifacts/{artifact_id}"
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")

    app.dependency_overrides[identity] = lambda: "bob"
    assert client.get(path).status_code == 404
    app.dependency_overrides[identity] = lambda: None
    assert client.get(path).status_code == 401
    assert client.get("/experimental/images/artifacts/../bad").status_code != 200


def test_artifact_route_not_mounted_without_store():
    app = FastAPI()
    app.include_router(build_image_router(
        FakeService(), authenticated_owner=lambda: "alice"
    ))
    client = TestClient(app)
    assert client.get("/experimental/images/artifacts/any").status_code == 404
