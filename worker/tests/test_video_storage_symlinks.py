"""Regression checks for nested media-directory symlink escapes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_storage import ExternalMediaStorage, MediaStorageUnavailable


class VideoStorageSymlinkTests(unittest.TestCase):
    def test_media_parent_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            base = Path(parent)
            root = base / "external"
            root.mkdir()
            target = base / "other"
            target.mkdir()
            try:
                (root / "Media").symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch.object(storage, "assert_ready"):
                with self.assertRaises(MediaStorageUnavailable):
                    storage.initialize_directories()
            self.assertFalse((target / "Images").exists())

    def test_leaf_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            base = Path(parent)
            root = base / "external"
            (root / "Media").mkdir(parents=True)
            target = base / "other"
            target.mkdir()
            try:
                (root / "Media" / "Videos").symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch.object(storage, "assert_ready"):
                with self.assertRaises(MediaStorageUnavailable):
                    storage.initialize_directories()


if __name__ == "__main__":
    unittest.main()
