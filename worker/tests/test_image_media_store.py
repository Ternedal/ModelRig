"""Unit tests for mounted image media storage boundary."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.image_media_store import ExternalMediaStore, MediaStorageError


class MediaStoreTests(unittest.TestCase):
    def _store(self, directory, *, min_free_bytes=0):
        with patch("app.image_media_store.os.path.ismount", return_value=True):
            return ExternalMediaStore(directory, [directory], min_free_bytes=min_free_bytes)

    def test_requires_explicit_external_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MediaStorageError):
                ExternalMediaStore(directory, [])
            with self.assertRaises(MediaStorageError):
                ExternalMediaStore(directory, ["/definitely-not-mounted"], min_free_bytes=0)

    def test_rejects_non_mount_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.image_media_store.os.path.ismount", return_value=False):
                with self.assertRaises(MediaStorageError):
                    ExternalMediaStore(directory, [directory], min_free_bytes=0)

    def test_round_trip_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            payload = b"fixture-image-data"
            result = store.publish(payload)
            self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(store.resolve(result["asset_id"], ".png").read_bytes(), payload)

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            with self.assertRaises(MediaStorageError):
                store.resolve("../etc/passwd", ".png")
            with self.assertRaises(MediaStorageError):
                store.publish(b"data", ".exe")

    def test_free_space_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MediaStorageError):
                self._store(directory, min_free_bytes=10**30)

    def test_symlink_asset_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            asset_id = "a" * 32
            (Path(directory) / (asset_id + ".png")).symlink_to(Path(directory) / "other")
            with self.assertRaises(MediaStorageError):
                store.resolve(asset_id, ".png")


if __name__ == "__main__":
    unittest.main()
