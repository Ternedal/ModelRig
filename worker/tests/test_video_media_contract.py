"""Tests for shared app media metadata; no local disk paths leaked."""
import unittest

from app.video_media_contract import MediaItem


class MediaContractTests(unittest.TestCase):
    def test_video_gallery_metadata(self):
        item = MediaItem(media_id="vid_1", kind="video")
        result = item.public_metadata()
        self.assertTrue(result["playback"]["supports_range"])
        self.assertNotIn("path", result)
        self.assertNotIn("root", result)

    def test_vr180_stereo_metadata(self):
        item = MediaItem(
            media_id="vr_1", kind="video", projection="equirectangular_180",
            stereo="left_right", thumbnail_id="thumb_1",
        )
        self.assertEqual(item.public_metadata()["stereo"], "left_right")

    def test_rejects_path_like_ids(self):
        with self.assertRaises(ValueError):
            MediaItem(media_id="../../secret", kind="video")

    def test_image_mime(self):
        item = MediaItem(media_id="img_1", kind="image", mime_type="image/png")
        self.assertFalse(item.public_metadata()["playback"]["supports_range"])


if __name__ == "__main__":
    unittest.main()
