"""Owner isolation and filesystem tests for image artifact storage."""
import pytest
from app.image_generation.artifacts import ImageArtifactStore


def test_owner_scoped_atomic_storage(tmp_path):
    store = ImageArtifactStore(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"test-reencoded-fixture"
    artifact_id = store.put_png("alice", payload)
    assert store.get_png("alice", artifact_id) == payload
    assert store.get_png("bob", artifact_id) is None
    assert store.get_png("alice", "../outside") is None


def test_rejects_non_png_and_oversize(tmp_path):
    store = ImageArtifactStore(tmp_path, max_bytes=40)
    with pytest.raises(ValueError):
        store.put_png("alice", b"not a png")
    with pytest.raises(ValueError):
        store.put_png("alice", b"\x89PNG\r\n\x1a\n" + b"x" * 100)
