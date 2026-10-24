"""Test that production job DB cannot fall back to local storage."""
import unittest
from unittest.mock import patch

from app.video_job_store import VideoJobStore
from app.video_storage import MediaStorageUnavailable


class ExternalVideoDatabaseTests(unittest.TestCase):
    def test_factory_fails_without_volume(self):
        with patch("app.video_job_store.configured_video_storage",
                   side_effect=MediaStorageUnavailable("volume offline")):
            with self.assertRaises(MediaStorageUnavailable):
                VideoJobStore.on_external_volume()


if __name__ == "__main__":
    unittest.main()
