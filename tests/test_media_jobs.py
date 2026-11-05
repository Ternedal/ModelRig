"""Offline lifecycle tests for the media job admission state machine."""
import unittest

from worker.app.media_jobs import MediaJobError, MediaJobQueue, MediaJobState


class MediaJobsTests(unittest.TestCase):
    def test_lifecycle(self):
        q = MediaJobQueue(capacity=2)
        job = q.submit("image")
        self.assertEqual(q.get(job.id).state, MediaJobState.QUEUED)
        q.start(job.id)
        with self.assertRaises(MediaJobError):
            q.cancel(job.id)
        q.complete(job.id, "render.png")
        self.assertEqual(q.get(job.id).output_name, "render.png")
        with self.assertRaises(MediaJobError):
            q.start(job.id)

    def test_capacity_and_concurrency(self):
        q = MediaJobQueue(capacity=2, max_active=1)
        first, second = q.submit("image"), q.submit("video")
        with self.assertRaises(MediaJobError):
            q.submit("image")
        q.start(first.id)
        with self.assertRaises(MediaJobError):
            q.start(second.id)
        q.fail(first.id, "timeout")
        q.start(second.id)
        q.complete(second.id, "clip.mp4")
        self.assertEqual(q.submit("image").state, MediaJobState.QUEUED)

    def test_rejects_invalid_transitions(self):
        q = MediaJobQueue()
        with self.assertRaises(MediaJobError):
            q.submit("audio")
        with self.assertRaises(MediaJobError):
            q.start("missing")
        job = q.submit("video")
        with self.assertRaises(MediaJobError):
            q.complete(job.id, "clip.mp4")
        q.cancel(job.id)
        with self.assertRaises(MediaJobError):
            q.fail(job.id)
        with self.assertRaises(MediaJobError):
            q.start(job.id)

    def test_invalid_output_names(self):
        q = MediaJobQueue()
        job = q.submit("image")
        q.start(job.id)
        for name in ("", "../escape", "nested/file", "nested\\file", ".."):
            with self.subTest(name=name), self.assertRaises(MediaJobError):
                q.complete(job.id, name)
        self.assertEqual(q.get(job.id).state, MediaJobState.RUNNING)


if __name__ == "__main__":
    unittest.main()
