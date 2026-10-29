"""Offline contract tests for the staged gallery catalog."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.app.media_gallery_catalog import (
    GalleryBadRequest, GalleryUnavailable, list_gallery,
)


class GalleryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "gallery-index.json").write_text(json.dumps([
            {"id": "img_1", "kind": "image", "mime_type": "image/png", "size_bytes": 10},
            {"id": "vid_2", "kind": "video", "mime_type": "video/mp4", "size_bytes": 20},
        ]), encoding="utf-8")

    def page(self, **kwargs):
        with patch("worker.app.media_gallery_catalog.os.path.ismount", return_value=True):
            return list_gallery(self.root, **kwargs)

    def test_pagination(self):
        first = self.page(limit=1)
        self.assertEqual(first["schema"], "kaliv-media-gallery/v1")
        self.assertEqual(first["next_cursor"], "img_1")
        self.assertEqual(self.page(cursor="img_1")["items"][0]["id"], "vid_2")

    def test_reject_bad_inputs(self):
        for limit in (0, 101, True, 1.5):
            with self.assertRaises(GalleryBadRequest):
                self.page(limit=limit)
        for cursor in ("../etc", "unknown", "x\n"):
            with self.assertRaises(GalleryBadRequest):
                self.page(cursor=cursor)

    def test_reject_duplicate_ids(self):
        (self.root / "gallery-index.json").write_text(
            json.dumps([{"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": 1}] * 2), encoding="utf-8")
        with self.assertRaises(GalleryUnavailable):
            self.page()

    def test_refuse_untrusted_metadata(self):
        bad_items = (
            {"id": "x", "kind": "image", "mime_type": "video/mp4", "size_bytes": 1},
            {"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": True},
            {"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": 1, "url": "https://attacker.example"},
        )
        for item in bad_items:
            with self.subTest(item=item):
                (self.root / "gallery-index.json").write_text(json.dumps([item]), encoding="utf-8")
                with self.assertRaises(GalleryUnavailable):
                    self.page()

    def test_refuse_unmounted_root(self):
        with patch("worker.app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(GalleryUnavailable):
                list_gallery(self.root)

    def test_refuse_symlink_index(self):
        (self.root / "gallery-index.json").unlink()
        target = self.root / "other.json"
        target.write_text("[]", encoding="utf-8")
        (self.root / "gallery-index.json").symlink_to(target)
        with self.assertRaises(GalleryUnavailable):
            self.page()


if __name__ == "__main__":
    unittest.main()
