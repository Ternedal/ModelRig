"""Offline reconciliation diagnostics: no automatic job-state transitions."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.image_job_store import ImageJobStore
from app.media_gallery_store import ExternalMediaSink
from app.media_generation_reconciliation import inspect_generation_consistency


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        volume = Path(tmp.name)
        media = volume / "media"
        media.mkdir()
        self.jobs = ImageJobStore(str(volume / "jobs.sqlite"))
        self.sink = ExternalMediaSink(media, volume)

    def submit_running(self):
        job_id = self.jobs.submit("owner", "prompt", profile_id="test")["job_id"]
        claimed = self.jobs.claim()
        self.assertEqual(claimed["id"], job_id)
        return job_id

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_running_with_published_unindexed_file_is_reported_without_mutation(self, _mount):
        job_id = self.submit_running()
        self.sink.publish_for_job(job_id, b"image", ".png")
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "running_with_unindexed_artifact")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "running")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_running_with_indexed_file_is_not_mislabeled_failed(self, _mount):
        job_id = self.submit_running()
        self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "running_with_indexed_artifact")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "running")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_completed_indexed_job_is_consistent(self, _mount):
        job_id = self.submit_running()
        asset = self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
        self.assertEqual(inspect_generation_consistency(self.jobs, self.sink)[0]["status"], "consistent")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_legacy_completed_job_is_not_misclassified_as_missing_deterministic_asset(self, _mount):
        job_id = self.submit_running()
        asset = self.sink.publish(b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "completed_non_job_scoped_asset")
        self.assertEqual(self.jobs.get(job_id, "owner")["asset_id"], asset)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_failed_job_with_indexed_file_is_flagged(self, _mount):
        job_id = self.submit_running()
        self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, error="interrupted"))
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "failed_with_indexed_artifact")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "failed")


if __name__ == "__main__":
    unittest.main()
