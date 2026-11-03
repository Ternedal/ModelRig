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

    def test_reconciliation_limit_rejects_invalid_values(self):
        for limit in (0, -1, 1001, True, 1.5, "10"):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, "invalid_reconciliation_limit"):
                    inspect_generation_consistency(self.jobs, self.sink, limit=limit)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_reconciliation_limit_caps_rows(self, _mount):
        for _ in range(3):
            self.jobs.submit("owner", "prompt", profile_id="test")
            self.jobs.claim()
        self.assertEqual(len(inspect_generation_consistency(self.jobs, self.sink, limit=2)), 2)
        self.assertEqual(len(inspect_generation_consistency(self.jobs, self.sink, limit=3)), 3)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_publishing_states_are_read_only_and_distinct(self, _mount):
        job_id = self.submit_running()
        # Simulate the forward-compatible G2 state on a real SQLite row.
        # Do not use a mocked cursor: the actual SELECT must include publishing.
        with self.jobs._db() as db:
            db.execute("UPDATE image_jobs SET state='publishing' WHERE id=?", (job_id,))
        before = self.jobs.get(job_id, "owner")
        self.assertEqual(inspect_generation_consistency(self.jobs, self.sink)[0]["status"],
                         "publishing_without_job_artifact")
        self.sink.publish_for_job(job_id, b"image", ".png")
        self.assertEqual(inspect_generation_consistency(self.jobs, self.sink)[0]["status"],
                         "publishing_with_unindexed_artifact")
        self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        self.assertEqual(inspect_generation_consistency(self.jobs, self.sink)[0]["status"],
                         "publishing_with_indexed_artifact")
        self.assertEqual(self.jobs.get(job_id, "owner"), before)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_publishing_indexed_missing_file_is_conflict_without_mutation(self, _mount):
        job_id = self.submit_running()
        with self.jobs._db() as db:
            db.execute("UPDATE image_jobs SET state='publishing' WHERE id=?", (job_id,))
        asset = self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        before = self.jobs.get(job_id, "owner")
        (self.sink.media_root / (asset + ".png")).unlink()
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "media_conflict")
        self.assertEqual(report[0]["reason"], "job_asset_missing_but_indexed")
        self.assertEqual(self.jobs.get(job_id, "owner"), before)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_bounded_scan_prefers_newest_jobs(self, _mount):
        older = self.submit_running()
        newer = self.submit_running()
        with self.jobs._db() as db:
            db.execute("UPDATE image_jobs SET created = ? WHERE id = ?", (100, older))
            db.execute("UPDATE image_jobs SET created = ? WHERE id = ?", (200, newer))
            db.commit()
        report = inspect_generation_consistency(self.jobs, self.sink, limit=1)
        self.assertEqual([item["job_id"] for item in report], [newer])
        self.assertNotEqual(older, newer)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_bounded_scan_includes_newer_stranded_publishing_job(self, _mount):
        older = self.submit_running()
        newer = self.submit_running()
        with self.jobs._db() as db:
            db.execute("UPDATE image_jobs SET created=? WHERE id=?", (100, older))
            db.execute("UPDATE image_jobs SET created=?,state='publishing' WHERE id=?", (200, newer))
        self.sink.publish_and_register_for_job(newer, b"image", ".png")
        before = self.jobs.get(newer, "owner")
        report = inspect_generation_consistency(self.jobs, self.sink, limit=1)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["job_id"], newer)
        self.assertEqual(report[0]["status"], "publishing_with_indexed_artifact")
        self.assertEqual(self.jobs.get(newer, "owner"), before)

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
        self.assertEqual(report[0]["status"], "completed_legacy_indexed")
        self.assertEqual(self.jobs.get(job_id, "owner")["asset_id"], asset)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_legacy_completed_jpeg_and_webp_are_indexed(self, _mount):
        # The new sink deliberately publishes PNG/MP4 only. Model older
        # producer-written assets directly; do not widen its write allowlist.
        import json
        import secrets
        index_path = self.sink.media_root / "gallery-index.json"
        for extension, mime in ((".jpg", "image/jpeg"), (".webp", "image/webp")):
            with self.subTest(extension=extension):
                with self.assertRaisesRegex(ValueError, "invalid_artifact_extension"):
                    self.sink.publish(b"image", extension)
                job_id = self.submit_running()
                asset = secrets.token_hex(16)
                (self.sink.media_root / (asset + extension)).write_bytes(b"image")
                entries = json.loads(index_path.read_text()) if index_path.exists() else []
                entries.append({
                    "id": asset, "kind": "image", "mime_type": mime,
                    "size_bytes": len(b"image"), "created_at": "2026-01-01T00:00:00Z",
                })
                index_path.write_text(json.dumps(entries))
                self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
                findings = inspect_generation_consistency(self.jobs, self.sink)
                match = next(item for item in findings if item["job_id"] == job_id)
                self.assertEqual(match["status"], "completed_legacy_indexed")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_legacy_completed_job_with_deleted_file_is_flagged(self, _mount):
        job_id = self.submit_running()
        asset = self.sink.publish(b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
        (self.sink.media_root / (asset + ".png")).unlink()
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "completed_legacy_missing_file")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "completed")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_completed_job_with_missing_artifact_is_flagged(self, _mount):
        job_id = self.submit_running()
        asset = self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
        (self.sink.media_root / (asset + ".png")).unlink()
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "media_conflict")
        self.assertEqual(report[0]["reason"], "job_asset_missing_but_indexed")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "completed")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_completed_job_with_unindexed_artifact_is_flagged(self, _mount):
        job_id = self.submit_running()
        asset = self.sink.publish_for_job(job_id, b"image", ".png")
        self.assertTrue(self.jobs.finish(job_id, asset_id=asset))
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "completed_not_indexed")
        self.assertEqual(self.jobs.get(job_id, "owner")["state"], "completed")

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_crash_after_publish_before_completion_is_reported_without_mutation(self, _mount):
        """Simulate a process dying after durable publication, before DB commit."""
        job_id = self.submit_running()
        asset = self.sink.publish_and_register_for_job(job_id, b"image", ".png")
        before = self.jobs.get(job_id, "owner")
        self.assertEqual(before["state"], "running")
        self.assertIsNone(before["asset_id"])
        report = inspect_generation_consistency(self.jobs, self.sink)
        self.assertEqual(report[0]["status"], "running_with_indexed_artifact")
        self.assertEqual(report[0]["asset_id"], asset)
        self.assertEqual(self.jobs.get(job_id, "owner"), before)
        self.assertEqual((self.sink.media_root / (asset + ".png")).read_bytes(), b"image")
        # A second inspection is idempotent; no false completion or cleanup.
        self.assertEqual(inspect_generation_consistency(self.jobs, self.sink), report)

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
