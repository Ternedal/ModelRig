"""Contract tests for the owner-scoped media catalog projection."""
import unittest

from worker.app.media_catalog_projection import (
    MediaCatalogProjectionError,
    owned_completed_media,
)


class MediaCatalogProjectionTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"asset_id": "mine", "mime": "image/png", "size": 4, "path": "NEVER_LEAK"},
            {"asset_id": "other", "mime": "video/mp4", "size": 8},
        ]

    def project(self, owned=frozenset({"mine"}), entries=None, **kwargs):
        return owned_completed_media(
            "installation", lambda owner: owned,
            lambda: self.entries if entries is None else entries, **kwargs
        )

    def test_only_completed_owned_and_no_path(self):
        self.assertEqual(self.project(), [{"asset_id": "mine", "mime": "image/png", "size": 4}])

    def test_empty_ownership(self):
        self.assertEqual(self.project(owned=frozenset()), [])

    def test_rejects_invalid_metadata_even_for_other_owner(self):
        for entry in (
            {"asset_id": "../escape", "mime": "image/png", "size": 1},
            {"asset_id": "other", "mime": "text/html", "size": 1},
            {"asset_id": "other", "mime": "video/mp4", "size": -1},
            {"asset_id": "other", "mime": "video/mp4", "size": True},
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
            self.project(entries=[self.entries[0], {"asset_id": "bad", "mime": "x", "size": 1}], limit=1)


if __name__ == "__main__":
    unittest.main()
