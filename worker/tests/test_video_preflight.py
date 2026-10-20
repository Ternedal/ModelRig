"""Offline checks for the read-only video preflight."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_preflight import check
from app.video_storage import ExternalMediaStorage


class VideoPreflightTests(unittest.TestCase):
    def test_missing_configuration_fails(self):
        report = check({})
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["storage"], "fail")

    def test_existing_root_passes_storage_but_not_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = ExternalMediaStorage(tmp, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "pass")
            self.assertFalse(report["ready"])
            self.assertTrue(report["limitations"])

    def test_symlinked_cache_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            try:
                (root / "Cache").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(str(exc))
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "fail")
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
