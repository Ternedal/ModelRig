"""Gallery client validation tests."""
import unittest

from app.video_gallery_client_contract import GalleryAsset, validate_api_origin


class GalleryClientContractTests(unittest.TestCase):
    def test_video_projection(self):
        asset = GalleryAsset.from_api({
            "id": "clip_1", "kind": "video",
            "url": "/api/v1/media/clip_1",
            "thumbnail_id": "thumb_1",
            "thumbnail_url": "/api/v1/media/thumb_1",
            "projection": "equirectangular_180", "stereo": "left_right",
        })
        self.assertEqual(asset.projection, "equirectangular_180")
        self.assertEqual(asset.stereo, "left_right")

    def test_rejects_external_playback_url(self):
        with self.assertRaises(ValueError):
            GalleryAsset.from_api({
                "id": "clip_1", "kind": "video",
                "url": "https://untrusted.example/clip.mp4",
            })

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            GalleryAsset.from_api({
                "id": "../secret", "kind": "image",
                "url": "/api/v1/media/../secret",
            })

    def test_rejects_oversized_id(self):
        with self.assertRaises(ValueError):
            GalleryAsset.from_api({
                "id": "a" * 129, "kind": "image",
                "url": "/api/v1/media/" + "a" * 129,
            })

    def test_rejects_thumbnail_without_url(self):
        with self.assertRaises(ValueError):
            GalleryAsset.from_api({
                "id": "image_1", "kind": "image",
                "url": "/api/v1/media/image_1",
                "thumbnail_id": "thumb_1",
                "thumbnail_url": None,
            })

    def test_https_origin(self):
        self.assertEqual(validate_api_origin("https://rig.example"), "https://rig.example")
        for origin in ("http://rig.example", "https://user:pass@rig.example",
                       "https://rig.example/path", "https://rig.example?x=1"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                validate_api_origin(origin)


if __name__ == "__main__":
    unittest.main()
