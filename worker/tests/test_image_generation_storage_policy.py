"""External media storage policy cannot silently fall back to local disk."""
import pytest

from app.image_generation.storage_policy import require_external_media_root


def test_explicit_external_volume_and_child_directory(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    assert require_external_media_root(
        volume / "generated" / "images", mounted_volume=volume
    ) == volume / "generated" / "images"


@pytest.mark.parametrize("root,volume", [
    (None, None),
    ("relative/images", "/tmp"),
    ("/tmp/images", None),
])
def test_missing_or_relative_configuration_fails(root, volume):
    with pytest.raises(ValueError):
        require_external_media_root(root, mounted_volume=volume)


def test_missing_volume_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        require_external_media_root(
            tmp_path / "not-mounted" / "images",
            mounted_volume=tmp_path / "not-mounted"
        )


def test_escape_and_volume_root_rejected(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    for root in (volume, tmp_path / "local" / "images"):
        with pytest.raises(ValueError):
            require_external_media_root(root, mounted_volume=volume)


def test_symlink_escape_rejected(tmp_path):
    volume = tmp_path / "external"
    volume.mkdir()
    outside = tmp_path / "system"
    outside.mkdir()
    (volume / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        require_external_media_root(
            volume / "escape" / "images", mounted_volume=volume
        )
