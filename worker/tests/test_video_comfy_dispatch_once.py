"""Offline operator dispatch admission tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_comfy_dispatch_once import dispatch_once


class DispatchOnceTests(unittest.TestCase):
    def test_missing_template_rejected_without_contacting_backend(self):
        with patch("app.video_comfy_dispatch_once.configured_video_storage") as storage, patch.dict(
            "os.environ", {"KALIV_COMFY_WORKFLOW_TEMPLATE": ""}, clear=False
        ), patch("app.video_comfy_dispatch_once.ComfyVideoClient") as client:
            storage.return_value.initialize_directories.return_value = {"jobs": Path("/unused")}
            with self.assertRaises(ValueError):
                dispatch_once()
            client.assert_not_called()

    def test_template_outside_external_volume_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "external"
            media.mkdir()
            template = root / "outside.json"
            template.write_text("{}", encoding="utf-8")
            with patch("app.video_comfy_dispatch_once.configured_video_storage") as storage, patch.dict(
                "os.environ", {"KALIV_COMFY_WORKFLOW_TEMPLATE": str(template)}, clear=False
            ), patch("app.video_comfy_dispatch_once.ComfyVideoClient") as client:
                storage.return_value.root = media
                storage.return_value.initialize_directories.return_value = {"jobs": media / "Jobs"}
                with self.assertRaises(ValueError):
                    dispatch_once()
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
