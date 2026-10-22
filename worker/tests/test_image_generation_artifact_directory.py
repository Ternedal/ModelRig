"""Private artifact store boundary regression tests."""
from app.image_generation.artifacts import ImageArtifactStore


def test_directory_cannot_be_read_as_artifact(tmp_path):
    store = ImageArtifactStore(tmp_path / "images")
    owner = "alice"
    artifact_id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    owner_dir = store.root / store._owner_hash(owner)
    owner_dir.mkdir()
    (owner_dir / (artifact_id + ".png")).mkdir()
    assert store.get_png(owner, artifact_id) is None
