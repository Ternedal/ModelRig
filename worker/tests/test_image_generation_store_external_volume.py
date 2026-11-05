"""External-volume policy is enforced at artifact store construction."""
import pytest

from app.image_generation.artifacts import ImageArtifactStore


def test_store_accepts_explicit_external_volume(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    store = ImageArtifactStore(volume / "images", external_volume=volume)
    assert store.root == volume / "images"
    assert store.root.is_dir()


def test_store_rejects_local_fallback_when_volume_missing(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        ImageArtifactStore(
            tmp_path / "missing" / "images",
            external_volume=tmp_path / "missing"
        )
    assert not (tmp_path / "missing").exists()


def test_store_rejects_root_outside_external_volume(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    with pytest.raises(ValueError, match="beneath"):
        ImageArtifactStore(
            tmp_path / "system" / "images",
            external_volume=volume
        )
    assert not (tmp_path / "system").exists()
