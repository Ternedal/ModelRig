"""Unit tests for the experimental video request and playback contract."""
import unittest

from app.video_contract import VideoRequest


class VideoContractTests(unittest.TestCase):
    def test_flat_text_video(self):
        req = VideoRequest(kind="text_to_video", prompt="Rainy city")
        manifest = req.flat_manifest("asset_123")
        self.assertEqual(manifest["projection"], "flat")
        self.assertEqual(manifest["stereo"], "mono")
        self.assertEqual(manifest["artifact_id"], "asset_123")

    def test_vr_profiles_are_not_mislabeled(self):
        for profile in ("stereo_sbs", "vr180", "vr360"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                VideoRequest(kind="text_to_video", prompt="Scene", output_profile=profile)

    def test_image_video_requires_asset_id(self):
        with self.assertRaises(ValueError):
            VideoRequest(kind="image_to_video", prompt="Animate")
        VideoRequest(kind="image_to_video", prompt="Animate", input_image_id="img_123")

    def test_image_video_rejects_non_string_asset_ids(self):
        for value in (123, 0, True, False, [], {}, ["img_123"], b"img_123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VideoRequest(kind="image_to_video", prompt="Animate", input_image_id=value)

    def test_image_video_rejects_invalid_string_asset_ids(self):
        for value in ("", "../escape", "é", "x" * 129, "a/b", "has space"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VideoRequest(kind="image_to_video", prompt="Animate", input_image_id=value)

    def test_bad_dimensions_and_types(self):
        for changes in ({"width": 513}, {"width": True}, {"fps": 31},
                        {"duration_seconds": 9}, {"height": 2048}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                VideoRequest(kind="text_to_video", prompt="Scene", **changes)

    def test_rejects_invalid_artifact_id(self):
        req = VideoRequest(kind="text_to_video", prompt="Scene")
        for value in ("../file", "", "é", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                req.flat_manifest(value)


if __name__ == "__main__":
    unittest.main()
