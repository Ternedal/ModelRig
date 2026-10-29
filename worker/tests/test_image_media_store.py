"""Unit tests for mounted image media storage boundary."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.image_media_store import ExternalMediaStore, MediaStorageError


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        # Fixtures use a temporary directory, not a real external mount.
        mount_patch = patch("app.image_media_store.os.path.ismount", return_value=True)
        mount_patch.start()
        self.addCleanup(mount_patch.stop)

    def _store(self, directory, *, min_free_bytes=0):
        return ExternalMediaStore(directory, [directory], min_free_bytes=min_free_bytes)

    def test_requires_explicit_external_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MediaStorageError):
                ExternalMediaStore(directory, [])
            with self.assertRaises(MediaStorageError):
                ExternalMediaStore(directory, ["/definitely-not-mounted"], min_free_bytes=0)

    def test_rejects_system_root_even_if_mounted(self):
        root = str(Path("/").resolve())
        with patch("app.image_media_store.os.path.ismount", return_value=True):
            with self.assertRaises(MediaStorageError):
                ExternalMediaStore(root, [root], min_free_bytes=0)

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

    def test_unplugged_mount_blocks_publish_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            asset = store.publish(b"fixture")
            with patch("app.image_media_store.os.path.ismount", return_value=False):
                with self.assertRaises(MediaStorageError):
                    store.publish(b"must-not-write")
                with self.assertRaises(MediaStorageError):
                    store.resolve(asset["asset_id"], ".png")
            self.assertEqual(len(list(Path(directory).glob("*.png"))), 1)

    def test_changed_mount_device_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store._device_id = -1  # Simulate a different volume at the same mount path.
            with self.assertRaises(MediaStorageError):
                store.publish(b"must-not-write")
            with self.assertRaises(MediaStorageError):
                store.resolve("a" * 32, ".png")
            self.assertFalse(list(Path(directory).glob("*.png")))

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            with self.assertRaises(MediaStorageError):
                store.resolve("../etc/passwd", ".png")
            with self.assertRaises(MediaStorageError):
                store.publish(b"data", ".exe")

    def test_rejects_malformed_payload_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            for payload in (None, "", "text", bytearray(b"image"), [], {}, 123):
                with self.subTest(payload=payload), self.assertRaises(MediaStorageError):
                    store.publish(payload)
            for extension in (None, b".png", 123, [], {}, ".exe"):
                with self.subTest(extension=extension), self.assertRaises(MediaStorageError):
                    store.publish(b"image", extension)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_resolve_rejects_non_string_ids_and_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            for value in (None, 123, [], {}, b"a" * 32):
                with self.subTest(asset_id=value), self.assertRaises(MediaStorageError):
                    store.resolve(value, ".png")
            for value in (None, 123, [], {}, b".png"):
                with self.subTest(extension=value), self.assertRaises(MediaStorageError):
                    store.resolve("a" * 32, value)

    def test_payload_preflight_preserves_free_space_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.image_media_store.shutil.disk_usage") as usage:
                usage.return_value.free = 100
                store = self._store(directory, min_free_bytes=80)
                with self.assertRaises(MediaStorageError):
                    store.publish(b"x" * 21)
                self.assertEqual(list(Path(directory).iterdir()), [])

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
