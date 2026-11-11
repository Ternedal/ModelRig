"""Contract tests for the owner-scoped media catalog projection.

Run: PYTHONPATH=worker python3 tests/worker_media_catalog_projection.py
"""
import unittest
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.media_catalog_adapter import list_owned_gallery, open_owned_gallery_asset
from app.media_catalog_projection import (
    MediaCatalogProjectionError,
    owned_completed_media,
    open_owned_completed_media,
)


class MediaCatalogProjectionTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"id": "mine", "mime_type": "image/png", "size_bytes": 4, "created_at": "2026-11-11T00:00:00Z"},
            {"id": "other", "mime_type": "video/mp4", "size_bytes": 8},
        ]

    def project(self, owned=frozenset({"mine"}), entries=None, **kwargs):
        return owned_completed_media(
            "installation", lambda owner: owned,
            lambda: self.entries if entries is None else entries, **kwargs
        )

    def test_only_completed_owned_and_no_path(self):
        self.assertEqual(self.project(), [{"id": "mine", "mime_type": "image/png", "size_bytes": 4, "created_at": "2026-11-11T00:00:00Z"}])

    def test_empty_ownership(self):
        self.assertEqual(self.project(owned=frozenset()), [])

    def test_rejects_invalid_metadata_even_for_other_owner(self):
        for entry in (
            {"id": "../escape", "mime_type": "image/png", "size_bytes": 1},
            {"id": "other", "mime_type": "text/html", "size_bytes": 1},
            {"id": "other", "mime_type": "video/mp4", "size_bytes": -1},
            {"id": "other", "mime_type": "video/mp4", "size_bytes": True},
        ):
            with self.subTest(entry=entry), self.assertRaises(MediaCatalogProjectionError):
                self.project(entries=[entry])

    def test_duplicate_asset_fails_closed(self):
        with self.assertRaises(MediaCatalogProjectionError):
            self.project(entries=[self.entries[0], self.entries[0]])

    def test_authority_error_fails_closed(self):
        with self.assertRaises(MediaCatalogProjectionError):
            owned_completed_media("installation", lambda owner: 1 / 0, lambda: self.entries)

    def test_invalid_owner_and_limit(self):
        for owner in ("", " ", "x" * 257):
            with self.assertRaises(MediaCatalogProjectionError):
                owned_completed_media(owner, lambda _: frozenset(), lambda: [])
        with self.assertRaises(MediaCatalogProjectionError):
            self.project(limit=True)

    def test_limit_does_not_skip_later_invalid_entries(self):
        with self.assertRaises(MediaCatalogProjectionError):
            self.project(entries=[self.entries[0], {"id": "bad", "mime_type": "x", "size_bytes": 1}], limit=1)

    def test_open_owned_descriptor_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.mp4"
            path.write_bytes(b"abcd")
            calls = []
            def verify():
                calls.append("verified")
            handle, mime, size = open_owned_completed_media(
                "installation", "mine",
                lambda owner, asset: owner == "installation" and asset == "mine",
                lambda asset: (path.open("rb"), "video/mp4", 4),
                verify, lambda handle, asset: None,
            )
            try:
                self.assertEqual((mime, size, handle.read()), ("video/mp4", 4, b"abcd"))
                self.assertEqual(calls, ["verified", "verified"])
            finally:
                handle.close()

    def test_open_rejects_foreign_owner_before_open(self):
        calls = []
        with self.assertRaises(MediaCatalogProjectionError):
            open_owned_completed_media(
                "installation", "foreign", lambda *_: False,
                lambda _: calls.append("opened"), lambda: None, lambda handle, asset: None,
            )
        self.assertEqual(calls, [])

    def test_open_rejects_stale_size_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.png"
            path.write_bytes(b"abc")
            opened = []
            def open_asset(_):
                handle = path.open("rb")
                opened.append(handle)
                return handle, "image/png", 4
            with self.assertRaises(MediaCatalogProjectionError):
                open_owned_completed_media(
                    "installation", "mine", lambda *_: True, open_asset, lambda: None, lambda handle, asset: None
                )
            self.assertTrue(opened[0].closed)

    def test_open_rejects_volume_loss_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.png"
            path.write_bytes(b"abc")
            opened = []
            calls = []
            def verify():
                calls.append(1)
                if len(calls) == 2:
                    raise OSError("unplugged")
            def open_asset(_):
                handle = path.open("rb")
                opened.append(handle)
                return handle, "image/png", 3
            with self.assertRaises(MediaCatalogProjectionError):
                open_owned_completed_media(
                    "installation", "mine", lambda *_: True, open_asset, verify, lambda handle, asset: None
                )
            self.assertTrue(opened[0].closed)

    def test_descriptor_refusal_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.png"
            path.write_bytes(b"abc")
            opened = []
            def open_asset(_):
                handle = path.open("rb")
                opened.append(handle)
                return handle, "image/png", 3
            def reject_descriptor(handle, asset):
                raise OSError("descriptor not on verified volume")
            with self.assertRaises(MediaCatalogProjectionError):
                open_owned_completed_media(
                    "installation", "mine", lambda *_: True, open_asset,
                    lambda: None, reject_descriptor,
                )
            self.assertTrue(opened[0].closed)

    def test_adapter_filters_actual_gallery_index(self):
        class Store:
            def completed_assets_for(self, owner):
                self_owner = owner
                assert self_owner == "installation"
                return frozenset({"mine"})
        with patch("app.media_catalog_adapter._root", return_value=Path("/verified/gallery")), \\
             patch("app.media_catalog_adapter._index", return_value=self.entries):
            result = list_owned_gallery("installation", Store(), "/verified/gallery", "/verified", Volume())
        self.assertEqual([item["id"] for item in result], ["mine"])

    def test_adapter_rejects_foreign_asset_without_opening(self):
        class Store:
            def owns_completed_asset(self, owner, asset):
                return False
        class Volume:
            def verify(self):
                return None
        with patch("app.media_catalog_adapter.open_asset") as opener:
            with self.assertRaises(MediaCatalogProjectionError):
                open_owned_gallery_asset(
                    "installation", "foreign", Store(), "/gallery", "/volume",
                    Volume(), lambda handle, asset: None,
                )
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
