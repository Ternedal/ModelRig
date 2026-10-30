"""Offline atomic gallery-index registration tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_index_writer import register_asset
from app.media_gallery_catalog import GalleryUnavailable, list_gallery


class IndexWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.volume = Path(self.temp.name)
        self.root = self.volume / "media"
        self.root.mkdir()
        self.mount = patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
        self.mount.start()
        self.addCleanup(self.mount.stop)

    def test_register_and_preserve_entries(self):
        (self.root / "first.png").write_bytes(b"12345")
        register_asset(self.root, self.volume, "first", ".png", 5)
        (self.root / "second.mp4").write_bytes(b"0123456789")
        register_asset(self.root, self.volume, "second", ".mp4", 10)
        items = list_gallery(self.root, verified_volume_root=self.volume)["items"]
        self.assertEqual([item["id"] for item in items], ["first", "second"])
        self.assertEqual(items[1]["mime_type"], "video/mp4")

    def test_refuse_duplicate_without_corrupting_index(self):
        register_asset(self.root, self.volume, "first", ".png", 5)
        before = (self.root / "gallery-index.json").read_bytes()
        register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual((self.root / "gallery-index.json").read_bytes(), before)
        (self.root / "first.mp4").write_bytes(b"12345")
        with self.assertRaisesRegex(GalleryUnavailable, "duplicate_index_id"):
            register_asset(self.root, self.volume, "first", ".mp4", 5)
        with self.assertRaisesRegex(GalleryUnavailable, "asset_size_mismatch"):
            register_asset(self.root, self.volume, "first", ".png", 6)
        self.assertEqual((self.root / "gallery-index.json").read_bytes(), before)

    def test_refuse_traversal_asset_id_before_filesystem_access(self):
        with self.assertRaisesRegex(ValueError, "invalid_asset_id"):
            register_asset(self.root, self.volume, "../outside", ".png", 5)
        with self.assertRaisesRegex(ValueError, "invalid_asset_id"):
            register_asset(self.root, self.volume, "", ".png", 5)
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_missing_or_wrong_size_asset(self):
        with self.assertRaisesRegex(GalleryUnavailable, "asset_unavailable"):
            register_asset(self.root, self.volume, "missing", ".png", 5)
        (self.root / "wrong.png").write_bytes(b"123")
        with self.assertRaisesRegex(GalleryUnavailable, "asset_size_mismatch"):
            register_asset(self.root, self.volume, "wrong", ".png", 5)
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_active_lock(self):
        (self.root / "first.png").write_bytes(b"12345")
        (self.root / ".gallery-index.lock").write_text("busy")
        with self.assertRaisesRegex(GalleryUnavailable, "gallery_index_locked"):
            register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_corrupt_index_without_replacing_it(self):
        (self.root / "first.png").write_bytes(b"12345")
        (self.root / "gallery-index.json").write_text("{invalid")
        with self.assertRaises(GalleryUnavailable):
            register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual((self.root / "gallery-index.json").read_text(), "{invalid")
        self.assertFalse((self.root / ".gallery-index.lock").exists())


if __name__ == "__main__":
    unittest.main()
