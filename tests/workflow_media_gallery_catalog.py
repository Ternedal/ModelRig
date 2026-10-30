"""Offline contract tests for the staged gallery catalog."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_catalog import (
    GalleryBadRequest, GalleryUnavailable, list_gallery,
)


class GalleryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "gallery-index.json").write_text(json.dumps([
            {"id": "img_1", "kind": "image", "mime_type": "image/png", "size_bytes": 10, "created_at": "2026-10-29T07:00:00Z"},
            {"id": "vid_2", "kind": "video", "mime_type": "video/mp4", "size_bytes": 20, "created_at": "2026-10-29T07:00:00Z"},
        ]), encoding="utf-8")

    def page(self, **kwargs):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            return list_gallery(self.root, **kwargs)

    def test_pagination(self):
        first = self.page(limit=1)
        self.assertEqual(first["schema"], "kaliv-media-gallery/v1")
        self.assertEqual(first["next_cursor"], "img_1")
        self.assertEqual(first["items"][0]["url"], "/api/v1/media/img_1")
        self.assertEqual(first["items"][0]["playback"]["supports_range"], False)
        self.assertEqual(self.page(cursor="img_1")["items"][0]["id"], "vid_2")

    def test_reject_bad_inputs(self):
        for limit in (0, 101, True, 1.5):
            with self.assertRaises(GalleryBadRequest):
                self.page(limit=limit)
        for cursor in ("../etc", "unknown", "x\n"):
            with self.assertRaises(GalleryBadRequest):
                self.page(cursor=cursor)

    def test_reject_duplicate_json_keys_and_nonfinite_constants(self):
        malformed = (
            '[{"id":"img_1","id":"vid_2"}]',
            '[{"id":"img_1","metadata":{"a":1,"a":2}}]',
            '[{"id":"img_1","size_bytes":NaN}]',
            '[{"id":"img_1","size_bytes":Infinity}]',
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                (self.root / "gallery-index.json").write_text(payload, encoding="utf-8")
                with self.assertRaises(GalleryUnavailable):
                    self.page()

    def test_reject_oversized_index_item_count(self):
        # Reject before validating individual records or allocating projected entries.
        (self.root / "gallery-index.json").write_text(
            json.dumps([{}] * 10001), encoding="utf-8"
        )
        with self.assertRaisesRegex(GalleryUnavailable, "index_item_limit"):
            self.page()

    def test_reject_duplicate_ids(self):
        (self.root / "gallery-index.json").write_text(
            json.dumps([{"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": 1, "created_at": "2026-10-29T07:00:00Z"}] * 2), encoding="utf-8")
        with self.assertRaises(GalleryUnavailable):
            self.page()

    def test_refuse_untrusted_metadata(self):
        bad_items = (
            {"id": "x", "kind": "image", "mime_type": "video/mp4", "size_bytes": 1},
            {"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": True, "created_at": "2026-10-29T07:00:00Z"},
            {"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": 1, "created_at": "2026-10-29T07:00:00Z", "url": "https://attacker.example"},
            {"id": "x", "kind": "image", "mime_type": "image/png", "size_bytes": 1, "created_at": "2026-10-29T07:00:00Z", "path": "/tmp/escape.png"},
        )
        for item in bad_items:
            with self.subTest(item=item):
                (self.root / "gallery-index.json").write_text(json.dumps([item]), encoding="utf-8")
                with self.assertRaises(GalleryUnavailable):
                    self.page()

    def test_created_at_matches_android_instant_parse(self):
        item = {"id": "img_1", "kind": "image", "mime_type": "image/png",
                "size_bytes": 10, "created_at": "2026-10-29T08:00:00Z"}
        valid = ("2026-10-29T08:00:00Z", "2026-10-29T08:00:00.5Z",
                 "2026-10-29T08:00:00.123456789Z")
        invalid = ("2026-10-29 08:00:00Z", "20261029T080000Z",
                   "2026-10-29T08:00Z", "2026-10-29T08Z",
                   "2026-W44-4T08:00:00Z", "2026-10-29T08:00:00,5Z",
                   "2026-10-29T08:00:00+00:00",
                   "2026-10-29T08:00:00.1234567890Z")
        for timestamp in valid:
            with self.subTest(valid=timestamp):
                item["created_at"] = timestamp
                (self.root / "gallery-index.json").write_text(json.dumps([item]), encoding="utf-8")
                self.assertEqual(self.page()["items"][0]["created_at"], timestamp)
        for timestamp in invalid:
            with self.subTest(invalid=timestamp):
                item["created_at"] = timestamp
                (self.root / "gallery-index.json").write_text(json.dumps([item]), encoding="utf-8")
                with self.assertRaises(GalleryUnavailable):
                    self.page()

    def test_explicit_volume_allows_subdirectory_not_itself_a_mount(self):
        gallery = self.root / "kaliv-media"
        gallery.mkdir()
        (gallery / "gallery-index.json").write_bytes((self.root / "gallery-index.json").read_bytes())
        with patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: p == self.root):
            self.assertEqual(list_gallery(gallery, verified_volume_root=self.root)["items"][0]["id"], "img_1")
            with self.assertRaisesRegex(GalleryUnavailable, "external_media_not_mounted"):
                list_gallery(gallery)

    def test_explicit_volume_rejects_outside_and_unmounted(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "gallery-index.json").write_text("[]", encoding="utf-8")
        volume = self.root / "volume"
        volume.mkdir()
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaisesRegex(GalleryUnavailable, "media_root_outside_volume"):
                list_gallery(outside, verified_volume_root=volume)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaisesRegex(GalleryUnavailable, "external_media_not_mounted"):
                list_gallery(outside, verified_volume_root=volume)

    def test_verified_volume_rejects_symlinked_parent(self):
        actual = self.root / "actual"
        actual.mkdir()
        gallery = actual / "gallery"
        gallery.mkdir()
        (gallery / "gallery-index.json").write_bytes(
            (self.root / "gallery-index.json").read_bytes()
        )
        linked = self.root / "linked"
        try:
            linked.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaisesRegex(GalleryUnavailable, "media_root_symlink_parent"):
                list_gallery(linked / "gallery", verified_volume_root=self.root)

    def test_verified_volume_rejects_symlinked_volume_root(self):
        actual = self.root / "real-volume"
        actual.mkdir()
        linked = self.root / "linked-volume"
        try:
            linked.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaises(GalleryUnavailable):
                list_gallery(self.root, verified_volume_root=linked)

    def test_explicit_volume_does_not_accept_untrusted_relative_path(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaisesRegex(GalleryUnavailable, "external_media_unavailable"):
                list_gallery("relative-media", verified_volume_root=self.root)

    @unittest.skipUnless(os.name == "nt", "native Windows volume semantics only")
    def test_windows_drive_root_and_subdirectory_without_mount_mock(self):
        # This test must exercise Windows os.path.ismount, not a patched value.
        # The temporary directory lives on a real mounted drive (e.g. E:\\).
        drive = Path(self.root.anchor)
        self.assertTrue(os.path.ismount(drive))
        self.assertFalse(os.path.ismount(self.root))
        self.assertEqual(
            list_gallery(self.root, verified_volume_root=drive)["items"][0]["id"],
            "img_1",
        )

    def test_refuse_unmounted_root(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(GalleryUnavailable):
                list_gallery(self.root)

    def test_refuse_symlinked_parent_of_media_root(self):
        parent_link = self.root / "linked-parent"
        actual_parent = self.root / "actual-parent"
        actual_parent.mkdir()
        media_root = actual_parent / "media"
        media_root.mkdir()
        parent_link.symlink_to(actual_parent, target_is_directory=True)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaises(GalleryUnavailable):
                list_gallery(parent_link / "media")

    def test_refuse_symlink_index(self):
        (self.root / "gallery-index.json").unlink()
        target = self.root / "other.json"
        target.write_text("[]", encoding="utf-8")
        (self.root / "gallery-index.json").symlink_to(target)
        with self.assertRaises(GalleryUnavailable):
            self.page()


if __name__ == "__main__":
    unittest.main()
