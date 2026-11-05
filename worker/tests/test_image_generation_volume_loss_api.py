"""External volume loss is a safe 503 rather than an internal server error."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api import build_image_router
from app.image_generation.artifacts import external_image_artifact_store


def test_gallery_and_download_fail_closed_when_external_volume_disappears(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    marker = volume / ".modelrig-volume-id"
    marker.write_text("0123456789abcdef")
    store = external_image_artifact_store(
        volume / "images", external_volume=volume,
        volume_marker="0123456789abcdef",
    )
    app = FastAPI()
    app.include_router(build_image_router(
        object(), authenticated_owner=lambda: "alice", artifact_store=store
    ))
    marker.unlink()
    client = TestClient(app)
    assert client.get("/experimental/images/artifacts").status_code == 503
    assert client.get(
        "/experimental/images/artifacts/00000000-0000-4000-8000-000000000000"
    ).status_code == 503
    assert client.get(
        "/experimental/images/artifacts/00000000-0000-4000-8000-000000000000/thumbnail"
    ).status_code == 503
