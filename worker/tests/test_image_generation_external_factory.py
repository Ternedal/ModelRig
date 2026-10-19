"""The deployment-facing image store factory never falls back to local storage."""
import pytest

from app.image_generation.artifacts import external_image_artifact_store


def test_external_factory_requires_mounted_volume(tmp_path):
    volume = tmp_path / "external"
    with pytest.raises(ValueError):
        external_image_artifact_store(
            tmp_path / "local" / "images", external_volume=volume, volume_marker="0123456789abcdef"
        )
    assert not (tmp_path / "local").exists()


def test_external_factory_uses_explicit_volume(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    (volume / ".modelrig-volume-id").write_text("0123456789abcdef")
    store = external_image_artifact_store(
        volume / "generated" / "images", external_volume=volume
    )
    assert store.root == volume / "generated" / "images"
    assert store.root.is_dir()

def test_external_factory_rejects_wrong_volume_marker(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    (volume / ".modelrig-volume-id").write_text("different-volume-1234")
    with pytest.raises(ValueError, match="identity mismatch"):
        external_image_artifact_store(
            volume / "images", external_volume=volume,
            volume_marker="0123456789abcdef",
        )
    assert not (volume / "images").exists()
