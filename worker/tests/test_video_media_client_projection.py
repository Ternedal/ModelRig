"""Tests for path-free client media projections."""
import unittest

from app.video_media_client_projection import gallery_item_for_client


class MediaClientProjectionTests(unittest.TestCase):
    def test_video_url(self):
        item = gallery_item_for_client({"id": "clip_1", "kind": "video", "thumbnail_id": "thumb_1"})
        self.assertEqual(item["url"], "/api/v1/media/clip_1")
        self.assertEqual(item["thumbnail_url"], "/api/v1/media/thumb_1")

    def test_operator_urls(self):
        item = gallery_item_for_client({"id": "clip_1", "thumbnail_id": "thumb_1"}, url_prefix="/experimental/media")
        self.assertEqual(item["url"], "/experimental/media/clip_1")
        self.assertEqual(item["thumbnail_url"], "/experimental/media/thumb_1")

    def test_rejects_untrusted_url_prefix(self):
        with self.assertRaises(ValueError):
            gallery_item_for_client({"id": "clip_1"}, url_prefix="//evil.example")

    def test_no_thumbnail(self):
        item = gallery_item_for_client({"id": "image_1", "kind": "image"})
        self.assertIsNone(item["thumbnail_url"])

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            gallery_item_for_client({"id": "../private"})

    def test_rejects_oversized_id(self):
        with self.assertRaises(ValueError):
            gallery_item_for_client({"id": "a" * 129})

    def test_rejects_oversized_thumbnail(self):
        with self.assertRaises(ValueError):
            gallery_item_for_client({"id": "valid", "thumbnail_id": "t" * 129})

    def test_no_mutation(self):
        original = {"id": "image_1"}
        gallery_item_for_client(original)
        self.assertNotIn("url", original)


if __name__ == "__main__":
    unittest.main()
