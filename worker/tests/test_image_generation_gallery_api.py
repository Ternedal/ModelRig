"""Gallery listing exposes only owner-scoped opaque image IDs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore


class Service:
    pass


def test_gallery_owner_isolation_and_download(tmp_path):
    store = ImageArtifactStore(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"test"
    alice_id = store.put_png("alice", payload)
    bob_id = store.put_png("bob", payload)
    app = FastAPI()

    def owner():
        return "alice"

    app.include_router(build_image_router(
        Service(), authenticated_owner=owner, artifact_store=store
    ))
    client = TestClient(app)
    response = client.get("/experimental/images/artifacts")
    assert response.status_code == 200
    assert response.json() == {"artifacts": [
        {"id": alice_id, "media_type": "image/png"}
    ]}
    assert bob_id not in response.text
    assert str(tmp_path) not in response.text
    assert client.get(
        f"/experimental/images/artifacts/{alice_id}"
    ).content == payload
    assert client.get(
        f"/experimental/images/artifacts/{bob_id}"
    ).status_code == 404
    assert client.get("/experimental/images/artifacts?limit=201").status_code == 422
    app.dependency_overrides[owner] = lambda: "bob"
    assert client.get("/experimental/images/artifacts").json() == {
        "artifacts": [{"id": bob_id, "media_type": "image/png"}]
    }
