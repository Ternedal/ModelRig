"""Gallery pagination never leaks artifacts across owners."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore


def test_gallery_pages_are_disjoint_and_owner_scoped(tmp_path):
    store = ImageArtifactStore(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"test"
    own = [store.put_png("alice", payload) for _ in range(5)]
    other = store.put_png("bob", payload)
    app = FastAPI()
    app.include_router(build_image_router(
        object(), authenticated_owner=lambda: "alice", artifact_store=store
    ))
    client = TestClient(app)
    first = client.get("/experimental/images/artifacts?limit=2&offset=0")
    second = client.get("/experimental/images/artifacts?limit=2&offset=2")
    third = client.get("/experimental/images/artifacts?limit=2&offset=4")
    assert first.status_code == second.status_code == third.status_code == 200
    ids = [
        item["id"]
        for response in (first, second, third)
        for item in response.json()["artifacts"]
    ]
    assert set(ids) == set(own)
    assert len(ids) == len(set(ids)) == 5
    assert other not in ids
    assert client.get(
        "/experimental/images/artifacts?offset=10001"
    ).status_code == 422
