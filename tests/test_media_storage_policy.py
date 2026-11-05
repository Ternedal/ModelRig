"""Offline contract checks for generated media storage policy."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.app.media_storage_policy import MediaStorageError, safe_media_target, validate_media_root, write_media_exclusive


class MediaStoragePolicyTests(unittest.TestCase):
    def test_missing_configuration_fails(self):
        for value in (None, "", "  "):
            with self.subTest(value=value), self.assertRaises(MediaStorageError):
                validate_media_root(value)

    def test_relative_path_fails(self):
        with self.assertRaises(MediaStorageError):
            validate_media_root("relative/media")

    def test_nonexistent_path_fails(self):
        with self.assertRaises(MediaStorageError):
            validate_media_root("/definitely-not-existing-modelrig-media-root")

    def test_filename_traversal_and_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in ("", ".", "..", "../escape", "nested/file", "nested\\file"):
                with self.subTest(filename=filename), self.assertRaises(MediaStorageError):
                    safe_media_target(root, filename)
            (root / "existing.png").write_bytes(b"test")
            with self.assertRaises(MediaStorageError):
                safe_media_target(root, "existing.png")
            self.assertEqual(safe_media_target(root, "new.png"), root / "new.png")

    def test_symlink_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alias.png").symlink_to(root / "missing.png")
            with self.assertRaises(MediaStorageError):
                safe_media_target(root, "alias.png")

    def test_exclusive_write_and_size_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("worker.app.media_storage_policy.validate_media_root", return_value=root):
                output = write_media_exclusive(root, "image.png", b"image", max_bytes=16)
                self.assertEqual(output.read_bytes(), b"image")
                with self.assertRaises(MediaStorageError):
                    write_media_exclusive(root, "image.png", b"second")
                with self.assertRaises(MediaStorageError):
                    write_media_exclusive(root, "oversize.png", b"too long", max_bytes=2)
                self.assertFalse((root / "oversize.png").exists())


if __name__ == "__main__":
    unittest.main()
