"""Tests for the video job lifecycle primitive."""
import unittest

from app.video_job_state import VideoJob, VideoJobState


class VideoJobStateTests(unittest.TestCase):
    def test_happy_path(self):
        job = VideoJob("job_1")
        job.transition(VideoJobState.RUNNING)
        job.transition(VideoJobState.COMPLETED)
        self.assertEqual(job.state, VideoJobState.COMPLETED)

    def test_queued_cancel(self):
        job = VideoJob("job_2")
        job.transition(VideoJobState.CANCELLED)
        self.assertEqual(job.state, VideoJobState.CANCELLED)

    def test_failure_requires_safe_code(self):
        job = VideoJob("job_3")
        job.transition(VideoJobState.RUNNING)
        with self.assertRaises(ValueError):
            job.transition(VideoJobState.FAILED)
        with self.assertRaises(ValueError):
            job.transition(VideoJobState.FAILED, error_code="../secret")
        job.transition(VideoJobState.FAILED, error_code="backend_unavailable")
        self.assertEqual(job.error_code, "backend_unavailable")

    def test_terminal_state_is_immutable(self):
        job = VideoJob("job_4")
        job.transition(VideoJobState.CANCELLED)
        with self.assertRaises(ValueError):
            job.transition(VideoJobState.RUNNING)

    def test_invalid_transition(self):
        job = VideoJob("job_5")
        with self.assertRaises(ValueError):
            job.transition(VideoJobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
