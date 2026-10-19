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

def test_external_store_rejects_unplugged_volume_after_start(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    marker = volume / ".modelrig-volume-id"
    marker.write_text("0123456789abcdef")
    store = external_image_artifact_store(
        volume / "images", external_volume=volume,
        volume_marker="0123456789abcdef",
    )
    marker.unlink()
    with pytest.raises(RuntimeError, match="unavailable"):
        store.put_png("alice", b"\\x89PNG\\r\\n\\x1a\\n" + b"data")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.get_png("alice", "00000000-0000-4000-8000-000000000000")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.list_png_ids("alice")

def test_external_store_rechecks_identity_before_atomic_publish(tmp_path, monkeypatch):
    volume = tmp_path / "external"
    volume.mkdir()
    marker = volume / ".modelrig-volume-id"
    marker.write_text("0123456789abcdef")
    store = external_image_artifact_store(
        volume / "images", external_volume=volume,
        volume_marker="0123456789abcdef",
    )
    import app.image_generation.artifacts as artifacts
    original_fsync = artifacts.os.fsync

    def unplug_before_publish(fd):
        original_fsync(fd)
        marker.unlink()

    monkeypatch.setattr(artifacts.os, "fsync", unplug_before_publish)
    with pytest.raises(RuntimeError, match="unavailable"):
        store.put_png("alice", b"\\x89PNG\\r\\n\\x1a\\n" + b"data")
    assert not list((volume / "images").rglob("*.png"))
    assert not list((volume / "images").rglob(".upload-*"))

def test_strict_constructor_rejects_missing_marker(tmp_path):
    from app.image_generation.artifacts import ImageArtifactStore
    volume = tmp_path / "external"
    volume.mkdir()
    with pytest.raises(ValueError, match="identity marker"):
        ImageArtifactStore(
            volume / "images", external_volume=volume,
            require_external_volume=True,
        )
    assert not (volume / "images").exists()

def test_missing_mount_path_fails_closed_at_runtime(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    (volume / ".modelrig-volume-id").write_text("0123456789abcdef")
    store = external_image_artifact_store(
        volume / "images", external_volume=volume,
        volume_marker="0123456789abcdef",
    )
    import shutil
    shutil.rmtree(volume)
    with pytest.raises(RuntimeError, match="unavailable"):
        store.list_png_ids("alice")
    assert not volume.exists()
