"""The experimental image mount must remain opt-in and fail closed."""
import pytest
from fastapi import FastAPI

from app.image_generation.production_mount import mount_experimental_images
from app.image_generation.artifacts import ImageArtifactStore


def test_default_mount_does_not_register_routes():
    app = FastAPI()
    assert mount_experimental_images(app) is False
    assert not any(route.path.startswith("/experimental/images") for route in app.routes)


@pytest.mark.parametrize("kwargs", [
    {},
    {"authenticated_owner": lambda: "alice"},
    {"authenticated_owner": lambda: "alice", "service": object()},
])
def test_enabled_mount_rejects_missing_dependencies(kwargs):
    app = FastAPI()
    with pytest.raises(RuntimeError):
        mount_experimental_images(app, enabled=True, **kwargs)
    assert not any(route.path.startswith("/experimental/images") for route in app.routes)


def test_enabled_mount_rejects_local_artifact_store(tmp_path):
    app = FastAPI()
    with pytest.raises(RuntimeError):
        mount_experimental_images(
            app, enabled=True, authenticated_owner=lambda: "alice",
            service=object(), artifact_store=ImageArtifactStore(tmp_path),
        )
    assert not any(route.path.startswith("/experimental/images") for route in app.routes)

def test_mount_rejects_permissive_store_even_with_external_marker(tmp_path):
    from app.image_generation.service import ImageGenerationService
    volume = tmp_path / "external"
    volume.mkdir()
    (volume / ".modelrig-volume-id").write_text("0123456789abcdef")
    store = ImageArtifactStore(
        volume / "images", external_volume=volume,
        volume_marker="0123456789abcdef",
        require_external_volume=False,
    )
    app = FastAPI()
    with pytest.raises(RuntimeError, match="marked external volume"):
        mount_experimental_images(
            app, enabled=True, authenticated_owner=lambda: "alice",
            service=object.__new__(ImageGenerationService), artifact_store=store,
        )
    assert not any(route.path.startswith("/experimental/images") for route in app.routes)
