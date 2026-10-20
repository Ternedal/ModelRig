"""Offline dispatcher regression tests: queue admission and backend correlation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.video_contract import VideoRequest
from app.video_dispatcher import VideoDispatcher
from app.video_job_store import VideoJobStore


class DispatcherOperatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = VideoJobStore(Path(self.directory.name) / "jobs.sqlite")
        self.client = Mock()
        self.client.submit_trusted_workflow.return_value = "prompt_123"
        self.workflow_factory = Mock(return_value={"node": {"class_type": "Example"}})
        self.ready = patch("app.video_dispatcher.configured_video_storage")
        self.storage = self.ready.start()
        self.storage.return_value.assert_ready = Mock()
        self.addCleanup(self.ready.stop)

    def test_valid_job_submits_and_persists_prompt(self):
        job_id = self.store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
        result = VideoDispatcher(self.store, self.client,
                                 self.workflow_factory).dispatch_one()
        self.assertEqual(result, "prompt_123")
        row = self.store.get(job_id)
        self.assertEqual(row["state"], "running")
        self.assertEqual(row["prompt_id"], "prompt_123")
        self.storage.return_value.assert_ready.assert_called_once_with()
        self.client.submit_trusted_workflow.assert_called_once()

    def test_missing_external_volume_leaves_job_queued(self):
        job_id = self.store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
        self.storage.return_value.assert_ready.side_effect = OSError("disk absent")
        with self.assertRaises(OSError):
            VideoDispatcher(self.store, self.client,
                            self.workflow_factory).dispatch_one()
        self.assertEqual(self.store.get(job_id)["state"], "queued")
        self.client.submit_trusted_workflow.assert_not_called()

    def test_backend_submission_failure_marks_job_failed(self):
        job_id = self.store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
        self.client.submit_trusted_workflow.side_effect = ValueError("invalid graph")
        self.assertIsNone(VideoDispatcher(self.store, self.client,
                                          self.workflow_factory).dispatch_one())
        row = self.store.get(job_id)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["error_code"], "submission_failed")
        self.assertIsNone(row["prompt_id"])

    def test_empty_queue_does_not_contact_backend(self):
        self.assertIsNone(VideoDispatcher(self.store, self.client,
                                          self.workflow_factory).dispatch_one())
        self.client.submit_trusted_workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
