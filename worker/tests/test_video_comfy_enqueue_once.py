"""Offline enqueue tests: validation before external-volume I/O."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_comfy_enqueue_once import enqueue
from app.video_job_store import VideoJobStore


class EnqueueTests(unittest.TestCase):
    def test_enqueue_creates_validated_external_job(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VideoJobStore(Path(directory) / "video_jobs.sqlite")
            with patch("app.video_comfy_enqueue_once.VideoJobStore.on_external_volume",
                       return_value=store) as factory:
                job_id = enqueue("Clouds", width=640, height=384, fps=16,
                                 duration_seconds=3)
                factory.assert_called_once_with()
            row = store.get(job_id)
            self.assertEqual(row["state"], "queued")
            self.assertIn('"width": 640', row["request_json"])
            self.assertIn('"duration_seconds": 3', row["request_json"])

    def test_invalid_request_never_opens_store(self):
        with patch("app.video_comfy_enqueue_once.VideoJobStore.on_external_volume") as factory:
            for args in (
                {"prompt": ""},
                {"prompt": "Clouds", "width": 513},
                {"prompt": "Clouds", "duration_seconds": 30},
                {"prompt": "Clouds", "fps": 0},
            ):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    enqueue(**args)
            factory.assert_not_called()

    def test_missing_external_volume_fails_closed(self):
        with patch("app.video_comfy_enqueue_once.VideoJobStore.on_external_volume",
                   side_effect=OSError("external disk missing")):
            with self.assertRaises(OSError):
                enqueue("Clouds")


if __name__ == "__main__":
    unittest.main()
