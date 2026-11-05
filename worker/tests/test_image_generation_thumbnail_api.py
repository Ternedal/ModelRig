"""Private thumbnails are decoded, resized and re-encoded without metadata."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import ImageArtifactStore


def test_thumbnail_is_small_and_owner_scoped(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    original = Image.new("RGB", (800, 400), (12, 30, 90))
    raw = io.BytesIO()
    original.save(raw, format="PNG")
    store = ImageArtifactStore(tmp_path)
    artifact_id = store.put_png("alice", raw.getvalue())
    app = FastAPI()

    def owner():
        return "alice"

    app.include_router(build_image_router(
        object(), authenticated_owner=owner, artifact_store=store
    ))
    client = TestClient(app)
    path = f"/experimental/images/artifacts/{artifact_id}/thumbnail"
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(response.content)) as thumb:
        assert thumb.size == (320, 160)
        assert thumb.format == "PNG"
        assert not thumb.info
    app.dependency_overrides[owner] = lambda: "bob"
    assert client.get(path).status_code == 404
