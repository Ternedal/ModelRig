"""Additional symlink guards for image artifact storage."""
import pytest

from app.image_generation.artifacts import ImageArtifactStore


def test_rejects_symlinked_root(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted")
    with pytest.raises(ValueError):
        ImageArtifactStore(link)


def test_rejects_symlinked_owner_on_read(tmp_path):
    store = ImageArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside"
    outside.mkdir()
    owner_dir = store.root / store._owner_hash("alice")
    try:
        owner_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted")
    assert store.get_png("alice", "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa") is None
