"""Offline test: no backend submission or job claim without external storage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_contract import VideoRequest
from app.video_dispatcher import VideoDispatcher
from app.video_job_store import VideoJobStore
from app.video_storage import MediaStorageUnavailable


class VideoDispatchStorageTests(unittest.TestCase):
    def test_missing_external_volume_keeps_job_queued(self):
        with tempfile.TemporaryDirectory() as temp:
            store = VideoJobStore(Path(temp) / "jobs.db")
            job_id = store.create(VideoRequest(kind="text_to_video", prompt="A lighthouse"))

            class ForbiddenBackend:
                def submit_trusted_workflow(self, workflow):
                    raise AssertionError("Backend must not be contacted")

            dispatcher = VideoDispatcher(store, ForbiddenBackend(), lambda request: {"1": {}})
            with patch("app.video_dispatcher.configured_video_storage",
                       side_effect=MediaStorageUnavailable("not mounted")):
                with self.assertRaises(MediaStorageUnavailable):
                    dispatcher.dispatch_one()
            self.assertEqual(store.get(job_id)["state"], "queued")


if __name__ == "__main__":
    unittest.main()
