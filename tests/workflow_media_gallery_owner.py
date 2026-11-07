"""Regression tests for the owner-only gallery projection."""
import io
import unittest
from unittest.mock import patch

from app.media_gallery_catalog import GalleryBadRequest, GalleryUnavailable
from app.media_gallery_owner import list_owned_gallery, open_owned_asset, stream_owned_asset, prepare_owned_asset_response
from app.media_gallery_asset import GalleryAssetNotFound


class Jobs:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.calls = []

    def owns_completed_asset(self, owner, asset_id):
        self.calls.append((owner, asset_id))
        return asset_id in self.allowed


class OwnerGalleryTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{"id": name, "url": "/api/v1/media/" + name}
                        for name in ("orphan", "one", "foreign", "two", "three")]
        self.root = patch("app.media_gallery_owner._root", return_value="/verified")
        self.index = patch("app.media_gallery_owner._index", return_value=self.entries)
        self.root.start()
        self.index.start()
        self.addCleanup(self.root.stop)
        self.addCleanup(self.index.stop)

    def test_filters_before_paging_and_keeps_cursor_private(self):
        jobs = Jobs({"one", "two", "three"})
        first = list_owned_gallery(jobs, "principal", "/media", limit=2, verified_volume_root="/volume")
        self.assertEqual([x["id"] for x in first["items"]], ["one", "two"])
        self.assertEqual(first["next_cursor"], "two")
        second = list_owned_gallery(jobs, "principal", "/media", cursor="two", limit=2, verified_volume_root="/volume")
        self.assertEqual([x["id"] for x in second["items"]], ["three"])
        self.assertIsNone(second["next_cursor"])
        self.assertTrue(all(owner == "principal" for owner, _ in jobs.calls))

    def test_thumbnail_reference_not_leaked(self):
        self.entries[1]["thumbnail_id"] = "foreign"
        self.entries[1]["thumbnail_url"] = "/api/v1/media/foreign"
        jobs = Jobs({"one"})
        result = list_owned_gallery(jobs, "principal", "/media", verified_volume_root="/volume")
        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["items"][0]["thumbnail_id"])
        self.assertIsNone(result["items"][0]["thumbnail_url"])
        self.assertEqual(self.entries[1]["thumbnail_id"], "foreign")

    def test_owned_thumbnail_preserved(self):
        self.entries[1]["thumbnail_id"] = "three"
        self.entries[1]["thumbnail_url"] = "/api/v1/media/three"
        result = list_owned_gallery(Jobs({"one", "three"}), "principal", "/media", verified_volume_root="/volume")
        self.assertEqual(result["items"][0]["thumbnail_id"], "three")

    def test_asset_read_foreign_and_unfinished_are_identical_not_found(self):
        jobs = Jobs({"one"})
        with patch("app.media_gallery_asset.open_asset") as opener:
            for asset_id in ("foreign", "orphan", "../escape"):
                with self.assertRaisesRegex(GalleryAssetNotFound, "unknown_asset"):
                    open_owned_asset(jobs, "principal", "/media", "/volume", asset_id)
            opener.assert_not_called()

    def test_asset_read_requires_verified_volume(self):
        with patch("app.media_gallery_asset.open_asset") as opener:
            with self.assertRaisesRegex(GalleryUnavailable, "verified_volume_required"):
                open_owned_asset(Jobs({"one"}), "principal", "/media", None, "one")
            opener.assert_not_called()

    def test_owned_asset_delegates_to_guarded_file_opener(self):
        with patch("app.media_gallery_asset.open_asset", return_value=("handle", {"id": "one"})) as opener:
            result = open_owned_asset(Jobs({"one"}), "principal", "/media", "/volume", "one")
        self.assertEqual(result[1]["id"], "one")
        opener.assert_called_once_with("/media", "/volume", "one")

    def test_open_owned_asset_redacts_foreign_thumbnail_without_mutation(self):
        raw = {"id": "one", "size_bytes": 4, "thumbnail_id": "foreign",
               "thumbnail_url": "/api/v1/media/foreign"}
        handle = io.BytesIO(b"abcd")
        with patch("app.media_gallery_asset.open_asset", return_value=(handle, raw)):
            opened, safe = open_owned_asset(Jobs({"one"}), "principal", "/media", "/volume", "one")
        self.assertIsNone(safe["thumbnail_id"])
        self.assertIsNone(safe["thumbnail_url"])
        self.assertEqual(raw["thumbnail_id"], "foreign")
        opened.close()

    def test_prepared_response_redacts_foreign_thumbnail(self):
        raw = {"id": "one", "size_bytes": 4, "thumbnail_id": "foreign",
               "thumbnail_url": "/api/v1/media/foreign"}
        with patch("app.media_gallery_asset.open_asset", return_value=(io.BytesIO(b"abcd"), raw)):
            safe, chunks = prepare_owned_asset_response(
                Jobs({"one"}), "principal", "/media", "/volume", "one")
        self.assertIsNone(safe["thumbnail_id"])
        self.assertIsNone(safe["thumbnail_url"])
        self.assertEqual(raw["thumbnail_id"], "foreign")
        chunks.close()

    def test_owned_asset_sanitizer_failure_closes_handle(self):
        class BrokenJobs(Jobs):
            def owns_completed_asset(self, owner, asset_id):
                if asset_id == "foreign":
                    raise RuntimeError("db unavailable")
                return super().owns_completed_asset(owner, asset_id)
        handle = io.BytesIO(b"abcd")
        raw = {"id": "one", "size_bytes": 4, "thumbnail_id": "foreign"}
        with patch("app.media_gallery_asset.open_asset", return_value=(handle, raw)):
            with self.assertRaisesRegex(RuntimeError, "db unavailable"):
                open_owned_asset(BrokenJobs({"one"}), "principal", "/media", "/volume", "one")
        self.assertTrue(handle.closed)

    def test_asset_read_without_principal_refused(self):
        with patch("app.media_gallery_asset.open_asset") as opener:
            with self.assertRaises(GalleryAssetNotFound):
                open_owned_asset(Jobs({"one"}), "", "/media", "/volume", "one")
            opener.assert_not_called()

    def test_stream_foreign_asset_never_opens(self):
        with patch("app.media_gallery_asset.open_asset") as opener:
            stream = stream_owned_asset(Jobs(set()), "principal", "/media", "/volume", "foreign")
            with self.assertRaisesRegex(GalleryAssetNotFound, "unknown_asset"):
                next(stream)
            opener.assert_not_called()

    def test_stream_checks_ownership_at_iteration_not_creation(self):
        jobs = Jobs({"one"})
        stream = stream_owned_asset(jobs, "principal", "/media", "/volume", "one")
        jobs.allowed.clear()
        with patch("app.media_gallery_asset.open_asset") as opener:
            with self.assertRaises(GalleryAssetNotFound):
                next(stream)
            opener.assert_not_called()

    def test_stream_owned_asset_closes_handle(self):
        handle = io.BytesIO(b"abc")
        with patch("app.media_gallery_asset.open_asset", return_value=(handle, {"size_bytes": 3})) as opener:
            self.assertEqual(b"".join(stream_owned_asset(Jobs({"one"}), "principal", "/media", "/volume", "one", chunk_size=2)), b"abc")
            opener.assert_called_once()
        self.assertTrue(handle.closed)

    def test_prepared_foreign_refused_eagerly(self):
        with patch("app.media_gallery_asset.open_asset") as opener:
            with self.assertRaises(GalleryAssetNotFound):
                prepare_owned_asset_response(Jobs(set()), "principal", "/media", "/volume", "foreign")
            opener.assert_not_called()

    def test_prepared_owned_entry_before_iteration_and_closes(self):
        handle = io.BytesIO(b"abcd")
        entry = {"id": "one", "size_bytes": 4}
        with patch("app.media_gallery_asset.open_asset", return_value=(handle, entry)):
            metadata, chunks = prepare_owned_asset_response(
                Jobs({"one"}), "principal", "/media", "/volume", "one", chunk_size=2)
        self.assertEqual(metadata["size_bytes"], 4)
        self.assertEqual(next(chunks), b"ab")
        chunks.close()
        self.assertTrue(handle.closed)

    def test_prepared_close_before_first_chunk(self):
        handle = io.BytesIO(b"abcd")
        with patch("app.media_gallery_asset.open_asset", return_value=(handle, {"size_bytes": 4})):
            _, chunks = prepare_owned_asset_response(
                Jobs({"one"}), "principal", "/media", "/volume", "one")
        chunks.close()
        self.assertTrue(handle.closed)

    def test_foreign_cursor_rejected(self):
        with self.assertRaisesRegex(GalleryBadRequest, "unknown_cursor"):
            list_owned_gallery(Jobs({"one"}), "principal", "/media", cursor="foreign", verified_volume_root="/volume")

    def test_missing_principal_refused(self):
        with self.assertRaisesRegex(GalleryBadRequest, "missing_authenticated_owner"):
            list_owned_gallery(Jobs({"one"}), "", "/media", verified_volume_root="/volume")

    def test_invalid_page_refused(self):
        with self.assertRaises(GalleryBadRequest):
            list_owned_gallery(Jobs({"one"}), "principal", "/media", limit=True, verified_volume_root="/volume")

    def test_missing_verified_volume_refused(self):
        with self.assertRaisesRegex(GalleryUnavailable, "verified_volume_required"):
            list_owned_gallery(Jobs({"one"}), "principal", "/media")

    def test_unavailable_volume_fails_closed(self):
        with patch("app.media_gallery_owner._root", side_effect=GalleryUnavailable("offline")):
            with self.assertRaises(GalleryUnavailable):
                list_owned_gallery(Jobs({"one"}), "principal", "/media", verified_volume_root="/volume")


if __name__ == "__main__":
    unittest.main()
