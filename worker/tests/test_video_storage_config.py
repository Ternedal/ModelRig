"""Offline checks for fail-closed video storage configuration."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_storage import MediaStorageUnavailable
from app.video_storage_config import configured_video_storage


class VideoStorageConfigTests(unittest.TestCase):
    def test_no_config_never_falls_back(self):
        with self.assertRaises(MediaStorageUnavailable):
            configured_video_storage({})

    def test_relative_root_is_rejected(self):
        with self.assertRaises(MediaStorageUnavailable):
            configured_video_storage({"KALIV_MEDIA_ROOT": "Kaliv/Media"})

    def test_missing_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(MediaStorageUnavailable):
                configured_video_storage({"KALIV_MEDIA_ROOT": str(Path(parent) / "absent")})

    def test_windows_resolved_system_drive_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch("app.video_storage_config.os") as mock_os, \
                 patch("app.video_storage_config.ExternalMediaStorage") as mock_storage:
                mock_os.name = "nt"
                mock_storage.return_value.root.drive = "C:"
                with self.assertRaisesRegex(MediaStorageUnavailable, "Resolved media root"):
                    configured_video_storage({"KALIV_MEDIA_ROOT": parent, "SystemDrive": "C:"})
                mock_storage.return_value.assert_ready.assert_not_called()

    def test_invalid_reserve_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(MediaStorageUnavailable):
                configured_video_storage({
                    "KALIV_MEDIA_ROOT": parent,
                    "KALIV_MEDIA_MIN_FREE_GB": "invalid",
                })


if __name__ == "__main__":
    unittest.main()
