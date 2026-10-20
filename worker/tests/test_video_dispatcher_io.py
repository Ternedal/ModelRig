"""Offline regression for dispatcher storage failures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_contract import VideoRequest
from app.video_dispatcher import VideoDispatcher
from app.video_job_store import VideoJobStore


class DispatcherIOTests(unittest.TestCase):
    def test_prompt_persistence_io_failure_marks_job_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VideoJobStore(Path(directory) / "jobs.sqlite")
            job_id = store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
            class Client:
                def submit_trusted_workflow(self, workflow):
                    return "prompt_123"
            dispatcher = VideoDispatcher(store, Client(), lambda request: {"node": {"class_type": "Example"}})
            with patch("app.video_dispatcher.configured_video_storage"), patch.object(
                store, "record_prompt", side_effect=OSError("disk unavailable")
            ):
                self.assertIsNone(dispatcher.dispatch_one())
            self.assertEqual(store.get(job_id)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
