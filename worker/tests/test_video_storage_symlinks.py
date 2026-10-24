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

    def test_provisions_expected_media_directories_on_approved_root(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch.object(storage, "assert_ready"):
                paths = storage.initialize_directories()
            self.assertEqual(set(paths), {"images", "videos", "vr", "jobs", "temp", "cache"})
            for name, path in paths.items():
                with self.subTest(name=name):
                    self.assertTrue(path.is_dir())
                    self.assertTrue(path.resolve().is_relative_to(root.resolve()))

    def test_late_symlink_rejected_before_any_media_directories_created(self):
        with tempfile.TemporaryDirectory() as parent:
            base = Path(parent)
            root = base / "external"
            root.mkdir()
            target = base / "other"
            target.mkdir()
            try:
                (root / "Cache").symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch.object(storage, "assert_ready"):
                with self.assertRaises(MediaStorageUnavailable):
                    storage.initialize_directories()
            self.assertFalse((root / "Media").exists())
            self.assertFalse((root / "Jobs").exists())
            self.assertEqual(list(target.iterdir()), [])

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
