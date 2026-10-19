"""Filesystem boundary regression for private image artifacts."""
import os

import pytest

from app.image_generation.artifacts import ImageArtifactStore


def test_rejects_symlinked_artifact(tmp_path):
    store = ImageArtifactStore(tmp_path / "artifacts")
    payload = b"\x89PNG\r\n\x1a\n" + b"fixture"
    artifact_id = store.put_png("alice", payload)
    owner_dir = store.root / store._owner_hash("alice")
    path = owner_dir / (artifact_id + ".png")
    target = tmp_path / "outside"
    target.write_bytes(b"secret")
    path.unlink()
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted")
    assert store.get_png("alice", artifact_id) is None


def test_rejects_symlinked_owner_directory(tmp_path):
    store = ImageArtifactStore(tmp_path / "artifacts")
    owner_dir = store.root / store._owner_hash("alice")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        owner_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted")
    with pytest.raises(ValueError):
        store.put_png("alice", b"\x89PNG\r\n\x1a\nfixture")
