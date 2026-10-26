"""Offline coordinator contracts, using only mocked ComfyUI I/O."""
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.app.media_coordinator import MediaCoordinator
from worker.app.media_jobs import MediaJobQueue, MediaJobState


class FakeTransport:
    def submit_prompt(self, workflow, client_id):
        return "prompt123"


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.queue = MediaJobQueue()
        self.coordinator = MediaCoordinator(self.queue, FakeTransport(), Path("/external"))

    def test_success(self):
        job_id = self.coordinator.submit("image", {"node": {}})
        with patch("worker.app.media_coordinator.poll_history", return_value={"state": "succeeded", "filenames": ["source.png"]}):
            with patch("worker.app.media_coordinator.import_comfy_output", return_value=Path("/external/render.png")) as imported:
                result = self.coordinator.poll(job_id)
        self.assertEqual(result.state, MediaJobState.SUCCEEDED)
        self.assertEqual(result.output_name, job_id + ".png")
        self.assertEqual(imported.call_args.args[3], job_id + ".png")

    def test_pending_then_failure(self):
        job_id = self.coordinator.submit("video", {"node": {}})
        with patch("worker.app.media_coordinator.poll_history", return_value={"state": "pending"}):
            self.assertEqual(self.coordinator.poll(job_id).state, MediaJobState.RUNNING)
        with patch("worker.app.media_coordinator.poll_history", return_value={"state": "failed"}):
            self.assertEqual(self.coordinator.poll(job_id).state, MediaJobState.FAILED)

    def test_wrong_output_format_fails_closed(self):
        job_id = self.coordinator.submit("video", {"node": {}})
        with patch("worker.app.media_coordinator.poll_history", return_value={"state": "succeeded", "filenames": ["image.png"]}):
            with patch("worker.app.media_coordinator.import_comfy_output") as imported:
                with self.assertRaises(Exception):
                    self.coordinator.poll(job_id)
                imported.assert_not_called()
        self.assertEqual(self.queue.get(job_id).state, MediaJobState.FAILED)


if __name__ == "__main__":
    unittest.main()
