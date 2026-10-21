"""Offline tests for the external media catalog and gallery contract."""
import tempfile
import unittest
from pathlib import Path

from app.video_media_catalog import MediaCatalog
from app.video_media_contract import MediaItem


class MediaCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for folder in ("Jobs", "Media/Images", "Media/Videos"):
            (self.root / folder).mkdir(parents=True)
        self.catalog = MediaCatalog(self.root)

    def test_gallery_and_resolution(self):
        path = self.root / "Media" / "Images" / "picture.png"
        path.write_bytes(b"example")
        self.catalog.register(MediaItem("img_1", "image", mime_type="image/png"), path)
        items = self.catalog.list_items()
        self.assertEqual([item["id"] for item in items], ["img_1"])
        resolved = self.catalog.resolve("img_1")
        self.assertEqual(resolved[0], path)
        self.assertNotIn("relative_path", items[0])

    def test_rejects_file_outside_media_root(self):
        path = self.root / "Jobs" / "private.mp4"
        path.write_bytes(b"example")
        with self.assertRaises(ValueError):
            self.catalog.register(MediaItem("vid_1", "video"), path)

    def test_rejects_mime_extension_mismatch(self):
        path = self.root / "Media" / "Images" / "wrong.jpg"
        path.write_bytes(b"example")
        with self.assertRaises(ValueError):
            self.catalog.register(MediaItem("img_1", "image", mime_type="image/png"), path)

    def test_rejects_traversal_ids(self):
        with self.assertRaises(ValueError):
            self.catalog.resolve("../private")

    def test_rejects_unsafe_catalog_paths(self):
        path = self.root / "Media" / "Videos" / "clip.mp4"
        path.write_bytes(b"example")
        self.catalog.register(MediaItem("vid_1", "video"), path)
        for unsafe in ("../secret.mp4", "/tmp/secret.mp4"):
            with self.subTest(path=unsafe):
                with self.catalog._connect() as db:
                    db.execute("UPDATE media_items SET relative_path=? WHERE media_id=?",
                               (unsafe, "vid_1"))
                with self.assertRaises(ValueError):
                    self.catalog.resolve("vid_1")

    def test_invalid_catalog_kind_fails_closed(self):
        path = self.root / "Media" / "Videos" / "clip.mp4"
        path.write_bytes(b"example")
        self.catalog.register(MediaItem("vid_1", "video"), path)
        with self.catalog._connect() as db:
            db.execute("UPDATE media_items SET kind=? WHERE media_id=?",
                       ("unknown", "vid_1"))
        with self.assertRaises(ValueError):
            self.catalog.resolve("vid_1")

    def test_missing_file_not_resolved(self):
        path = self.root / "Media" / "Videos" / "clip.mp4"
        path.write_bytes(b"example")
        self.catalog.register(MediaItem("vid_1", "video"), path)
        path.unlink()
        self.assertIsNone(self.catalog.resolve("vid_1"))


if __name__ == "__main__":
    unittest.main()
