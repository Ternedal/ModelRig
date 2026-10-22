"""Owner isolation tests for image job status and media asset lookup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.image_job_store import ImageJobStore
from app.image_media_store import ExternalMediaStore
from app.image_asset_service import ImageAssetService, ImageAssetNotFound


class ImageAssetServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.jobs = ImageJobStore(str(root / "jobs.sqlite3"))
        mount_patch = patch("app.image_media_store.os.path.ismount", return_value=True)
        mount_patch.start()
        self.addCleanup(mount_patch.stop)
        self.media = ExternalMediaStore(str(root), [str(root)], min_free_bytes=0)
        self.service = ImageAssetService(self.jobs, self.media)

    def test_owner_isolation(self):
        job = self.jobs.submit("owner-a", "private prompt")
        claimed = self.jobs.claim()
        asset = self.media.publish(b"fixture", ".png")
        self.assertTrue(self.jobs.finish(claimed["id"], asset_id=asset["asset_id"]))
        self.assertIsNone(self.service.get_job(job["job_id"], "owner-b"))
        with self.assertRaises(ImageAssetNotFound):
            self.service.get_asset(asset["asset_id"], "owner-b")
        own = self.service.get_asset(asset["asset_id"], "owner-a")
        self.assertEqual(own.path.read_bytes(), b"fixture")
        self.assertEqual(own.media_type, "image/png")

    def test_job_dto_excludes_prompt(self):
        job = self.jobs.submit("owner-a", "private prompt")
        dto = self.service.get_job(job["job_id"], "owner-a")
        self.assertEqual(dto["status"], "queued")
        self.assertNotIn("prompt", dto)
        self.assertNotIn("path", dto)

    def test_unlinked_asset_rejected(self):
        asset = self.media.publish(b"unlinked")
        with self.assertRaises(ImageAssetNotFound):
            self.service.get_asset(asset["asset_id"], "owner-a")


if __name__ == "__main__":
    unittest.main()
