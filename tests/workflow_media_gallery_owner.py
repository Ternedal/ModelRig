"""Regression tests for the owner-only gallery projection."""
import unittest
from unittest.mock import patch

from app.media_gallery_catalog import GalleryBadRequest, GalleryUnavailable
from app.media_gallery_owner import list_owned_gallery


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
        first = list_owned_gallery(jobs, "principal", "/media", limit=2)
        self.assertEqual([x["id"] for x in first["items"]], ["one", "two"])
        self.assertEqual(first["next_cursor"], "two")
        second = list_owned_gallery(jobs, "principal", "/media", cursor="two", limit=2)
        self.assertEqual([x["id"] for x in second["items"]], ["three"])
        self.assertIsNone(second["next_cursor"])
        self.assertTrue(all(owner == "principal" for owner, _ in jobs.calls))

    def test_foreign_cursor_rejected(self):
        with self.assertRaisesRegex(GalleryBadRequest, "unknown_cursor"):
            list_owned_gallery(Jobs({"one"}), "principal", "/media", cursor="foreign")

    def test_missing_principal_refused(self):
        with self.assertRaisesRegex(GalleryBadRequest, "missing_authenticated_owner"):
            list_owned_gallery(Jobs({"one"}), "", "/media")

    def test_invalid_page_refused(self):
        with self.assertRaises(GalleryBadRequest):
            list_owned_gallery(Jobs({"one"}), "principal", "/media", limit=True)

    def test_unavailable_volume_fails_closed(self):
        with patch("app.media_gallery_owner._root", side_effect=GalleryUnavailable("offline")):
            with self.assertRaises(GalleryUnavailable):
                list_owned_gallery(Jobs({"one"}), "principal", "/media")


if __name__ == "__main__":
    unittest.main()
