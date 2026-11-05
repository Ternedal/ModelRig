"""Offline checks for media coordinator concurrency and failed submissions."""
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.app.media_coordinator import MediaCoordinator
from worker.app.media_jobs import MediaJobQueue, MediaJobError, MediaJobState


class Transport:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def submit_prompt(self, workflow, client_id):
        self.calls += 1
        if self.fail:
            raise RuntimeError("ComfyUI down")
        return "prompt123"


class AdmissionTests(unittest.TestCase):
    def test_second_submission_must_not_reach_comfyui_when_worker_busy(self):
        transport = Transport()
        queue = MediaJobQueue(capacity=2, max_active=1)
        coordinator = MediaCoordinator(queue, transport, Path("/external"))
        coordinator.submit("image", {"node": {}})
        with self.assertRaises(MediaJobError):
            coordinator.submit("video", {"node": {}})
        self.assertEqual(transport.calls, 1)

    def test_failed_submission_is_terminal(self):
        transport = Transport(fail=True)
        queue = MediaJobQueue()
        coordinator = MediaCoordinator(queue, transport, Path("/external"))
        with self.assertRaises(RuntimeError):
            coordinator.submit("image", {"node": {}})
        self.assertEqual(transport.calls, 1)
        self.assertEqual(len(queue._jobs), 1)
        self.assertEqual(next(iter(queue._jobs.values())).state, MediaJobState.FAILED)


if __name__ == "__main__":
    unittest.main()
