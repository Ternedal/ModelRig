"""Offline regression tests for staged media request validation."""
import unittest

from scripts.media_request_validation import validate_request


class MediaRequestValidationTests(unittest.TestCase):
    def test_valid_text_and_image_requests(self):
        for kind in ("text_to_image", "text_to_video"):
            self.assertEqual(validate_request({"kind": kind, "prompt": "  sunset  "})["prompt"], "sunset")
        for kind in ("image_to_image", "image_to_video"):
            self.assertEqual(
                validate_request({"kind": kind, "prompt": "Animate", "input_image_id": "asset_123"})["input_image_id"],
                "asset_123",
            )

    def test_rejects_invalid_image_id_types(self):
        for bad in (None, True, 123, [], {}, "../secret", "é", "", "a" * 129):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "invalid_input_image_id"):
                validate_request({"kind": "image_to_video", "prompt": "Animate", "input_image_id": bad})

    def test_rejects_unexpected_fields_and_image_ids(self):
        for request in (
            {"kind": "text_to_video", "prompt": "scene", "input_image_id": "asset"},
            {"kind": "text_to_image", "prompt": "scene", "token": "secret"},
            {"kind": "image_to_video", "prompt": "scene"},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate_request(request)

    def test_rejects_bad_prompt_and_request_types(self):
        for request in (None, [], {}, {"kind": "text_to_image", "prompt": ""}, {"kind": "text_to_video", "prompt": 123}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate_request(request)


if __name__ == "__main__":
    unittest.main()
