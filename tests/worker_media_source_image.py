"""Offline regressions for the read-only image source seam."""
import os
import sqlite3
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_store import ExternalMediaSink
from app.media_source_image import read_source_png, read_owned_source_png
from app.image_job_store import ImageJobStore
from app.media_generation_contract import ArtifactSinkUnavailable, SourceImageUnavailable


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


# A genuine, decodable 1x1 RGB PNG, not just a matching signature.
PNG = (bytes.fromhex("89504e470d0a1a0a")
       + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
       + _png_chunk(b"IDAT", zlib.compress(bytes.fromhex("00ff0000")))
       + _png_chunk(b"IEND", b""))


class SourceImageTests(unittest.TestCase):
    def test_fixture_is_real_png_signature(self):
        self.assertEqual(PNG[:8], bytes.fromhex("89504e470d0a1a0a"))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        volume = Path(tmp.name)
        media = volume / "media"
        media.mkdir()
        self.sink = ExternalMediaSink(media, volume)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_indexed_png_is_read_without_modification(self, _mount):
        asset_id = self.sink.publish(PNG, ".png")
        self.assertEqual(read_source_png(self.sink, asset_id), PNG)
        self.assertEqual((self.sink.media_root / (asset_id + ".png")).read_bytes(), PNG)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_unindexed_png_refused(self, _mount):
        asset_id = "a" * 32
        (self.sink.media_root / (asset_id + ".png")).write_bytes(PNG)
        with self.assertRaises(SourceImageUnavailable):
            read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_symlink_source_refused(self, _mount):
        asset_id = self.sink.publish(PNG, ".png")
        path = self.sink.media_root / (asset_id + ".png")
        target = self.sink.media_root / "target.png"
        path.rename(target)
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(SourceImageUnavailable):
            read_source_png(self.sink, asset_id)
        # Windows lacks O_NOFOLLOW; static symlinks must still fail closed.
        with patch.object(os, "O_NOFOLLOW", 0, create=True):
            with self.assertRaises(SourceImageUnavailable):
                read_source_png(self.sink, asset_id)
        self.assertEqual(target.read_bytes(), PNG)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_corrupt_crc_and_truncated_png_refused(self, _mount):
        for bad in (PNG[:-5], PNG[:-12], PNG[:8] + b"junk", PNG[:-1] + bytes([PNG[-1] ^ 1])):
            with self.subTest(length=len(bad)):
                asset_id = self.sink.publish(bad, ".png")
                with self.assertRaises(SourceImageUnavailable):
                    read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_oversized_dimensions_refused(self, _mount):
        oversized = (PNG[:8] + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 9000, 1, 8, 2, 0, 0, 0))
                     + PNG[33:])
        asset_id = self.sink.publish(oversized, ".png")
        with self.assertRaises(SourceImageUnavailable):
            read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_invalid_png_chunk_order_and_color_depth_refused(self, _mount):
        sig = PNG[:8]
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        invalid_depth = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 4, 2, 0, 0, 0))
        idat = _png_chunk(b"IDAT", zlib.compress(bytes.fromhex("00ff0000")))
        end = _png_chunk(b"IEND", b"")
        bad_images = (
            sig + invalid_depth + idat + end,
            sig + ihdr + idat + _png_chunk(b"tEXt", b"k\\x00v") + idat + end,
            sig + ihdr + idat + _png_chunk(b"PLTE", b"\\x00\\x00\\x00") + end,
            sig + ihdr + _png_chunk(b"ABcD", b"") + idat + end,
            sig + ihdr + _png_chunk(b"1bad", b"") + idat + end,
        )
        for bad in bad_images:
            with self.subTest(length=len(bad)):
                asset_id = self.sink.publish(bad, ".png")
                with self.assertRaises(SourceImageUnavailable):
                    read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_png_metadata_and_palette_limits_refused(self, _mount):
        sig = PNG[:8]
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        indexed = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 1, 3, 0, 0, 0))
        idat = _png_chunk(b"IDAT", zlib.compress(bytes.fromhex("00ff0000")))
        end = _png_chunk(b"IEND", b"")
        bad_images = (
            sig + ihdr + _png_chunk(b"tEXt", b"x" * (4 * 1024 * 1024 + 1)) + idat + end,
            sig + ihdr + _png_chunk(b"tEXt", b"") * 4096 + idat + end,
            sig + indexed + _png_chunk(b"PLTE", bytes(9)) + idat + end,
        )
        for bad in bad_images:
            with self.subTest(length=len(bad)):
                asset_id = self.sink.publish(bad, ".png")
                with self.assertRaises(SourceImageUnavailable):
                    read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_owner_guard_requires_completed_matching_job(self, _mount):
        jobs = ImageJobStore(str(self.sink.volume_root / "jobs.sqlite"))
        asset_id = self.sink.publish(PNG, ".png")
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", asset_id)
        claimed = jobs.claim()
        self.assertEqual(claimed["id"], created["job_id"])
        self.assertTrue(jobs.finish(created["job_id"], asset_id=asset_id))
        self.assertEqual(read_owned_source_png(self.sink, jobs, "owner-a", asset_id), PNG)
        for owner in ("owner-b", "", None):
            with self.subTest(owner=owner), self.assertRaises(SourceImageUnavailable):
                read_owned_source_png(self.sink, jobs, owner, asset_id)
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", "a" * 32)
        for invalid_owner in (True, 123, "owner-a' OR 1=1 --"):
            with self.subTest(owner=invalid_owner), self.assertRaises(SourceImageUnavailable):
                read_owned_source_png(self.sink, jobs, invalid_owner, asset_id)
        failed = jobs.submit("owner-a", "failed prompt", profile_id="test")
        jobs.claim()
        self.assertTrue(jobs.finish(failed["job_id"], error="generation_failed"))
        self.assertFalse(jobs.owns_completed_asset("owner-a", "b" * 32))
        cancelled = jobs.submit("owner-a", "cancelled prompt", profile_id="test")
        self.assertTrue(jobs.cancel(cancelled["job_id"], "owner-a"))
        self.assertFalse(jobs.owns_completed_asset("owner-a", "c" * 32))
        interrupted = jobs.submit("owner-a", "interrupted prompt", profile_id="test")
        self.assertEqual(jobs.claim()["id"], interrupted["job_id"])
        self.assertEqual(jobs.recover_interrupted(), 1)
        self.assertFalse(jobs.owns_completed_asset("owner-a", "d" * 32))
        self.assertEqual(jobs.get(interrupted["job_id"], "owner-a")["state"], "failed")
        # Even a stale/corrupt artifact pointer on a noncompleted job must
        # never grant access to a valid, indexed source image.
        with sqlite3.connect(jobs.path) as db:
            db.execute(
                "UPDATE image_jobs SET asset_id=? WHERE id IN (?,?,?)",
                (asset_id, failed["job_id"], cancelled["job_id"], interrupted["job_id"]),
            )
        for job in (failed, cancelled, interrupted):
            self.assertEqual(jobs.get(job["job_id"], "owner-a")["asset_id"], asset_id)
        # A separate owner with only failed/cancelled jobs cannot borrow access.
        with sqlite3.connect(jobs.path) as db:
            db.execute(
                "UPDATE image_jobs SET owner=? WHERE id IN (?,?,?)",
                ("owner-b", failed["job_id"], cancelled["job_id"], interrupted["job_id"]),
            )
        self.assertFalse(jobs.owns_completed_asset("owner-b", asset_id))
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-b", asset_id)
        self.assertEqual(read_owned_source_png(self.sink, jobs, "owner-a", asset_id), PNG)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_g2_migration_preserves_owner_index_and_completed_authorization(self, _mount):
        """A G2-style schema upgrade must retain the owner lookup index."""
        jobs = ImageJobStore(str(self.sink.volume_root / "jobs.sqlite"))
        with sqlite3.connect(jobs.path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(image_jobs)")}
            indexes = {row[1] for row in db.execute("PRAGMA index_list(image_jobs)")}
            self.assertIn("claimed_by", columns)
            self.assertIn("cancel_requested", columns)
            self.assertIn("image_jobs_owner_asset_state", indexes)
            index_columns = [
                row[2] for row in db.execute(
                    "PRAGMA index_info(image_jobs_owner_asset_state)"
                )
            ]
            self.assertEqual(index_columns, ["owner", "asset_id", "state"])
        asset_id = self.sink.publish(PNG, ".png")
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        self.assertEqual(jobs.claim()["id"], created["job_id"])
        self.assertTrue(jobs.finish(created["job_id"], asset_id=asset_id))
        self.assertTrue(jobs.owns_completed_asset("owner-a", asset_id))
        self.assertFalse(jobs.owns_completed_asset("owner-b", asset_id))
        # Reinitializing must be idempotent and must not lose completed rows.
        reopened = ImageJobStore(str(jobs.path))
        self.assertTrue(reopened.owns_completed_asset("owner-a", asset_id))

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_g2_executor_only_grants_source_after_complete(self, _mount):
        """Exercise actual G2 transitions rather than synthetic SQLite state."""
        jobs = ImageJobStore(str(self.sink.volume_root / "g2_executor_jobs.sqlite"))
        asset_id = self.sink.publish(PNG, ".png")
        instance = "GPU-00000000-0000-0000-0000-000000000001:0123456789abcdef"
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        claimed = jobs.claim_for(["test"], instance)
        self.assertEqual(claimed["id"], created["job_id"])
        self.assertFalse(jobs.owns_completed_asset("owner-a", asset_id))
        self.assertTrue(jobs.begin_publish(created["job_id"], instance))
        self.assertFalse(jobs.owns_completed_asset("owner-a", asset_id))
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", asset_id)
        self.assertTrue(jobs.complete(created["job_id"], instance, asset_id))
        self.assertTrue(jobs.owns_completed_asset("owner-a", asset_id))
        self.assertEqual(read_owned_source_png(self.sink, jobs, "owner-a", asset_id), PNG)
        self.assertFalse(jobs.owns_completed_asset("owner-b", asset_id))

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_g2_publishing_and_recovered_publication_never_authorize_source(self, _mount):
        """A published file alone is insufficient until G2 commits completion."""
        jobs = ImageJobStore(str(self.sink.volume_root / "publishing_jobs.sqlite"))
        asset_id = self.sink.publish(PNG, ".png")
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        self.assertEqual(jobs.claim()["id"], created["job_id"])
        # Model an executor after begin_publish: the bytes exist but the job
        # has not committed the completed transition.
        with sqlite3.connect(jobs.path) as db:
            db.execute(
                "UPDATE image_jobs SET state='publishing',asset_id=? WHERE id=?",
                (asset_id, created["job_id"]),
            )
        self.assertFalse(jobs.owns_completed_asset("owner-a", asset_id))
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", asset_id)
        # A crash during publication leaves a failed row and an orphaned file;
        # neither the rightful owner nor another owner may consume it as I2V.
        with sqlite3.connect(jobs.path) as db:
            db.execute(
                "UPDATE image_jobs SET state='failed',"
                "error='interrupted during publication' WHERE id=?",
                (created["job_id"],),
            )
        for owner in ("owner-a", "owner-b"):
            with self.subTest(owner=owner):
                self.assertFalse(jobs.owns_completed_asset(owner, asset_id))
                with self.assertRaises(SourceImageUnavailable):
                    read_owned_source_png(self.sink, jobs, owner, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_legacy_database_upgrades_without_losing_completed_owner(self, _mount):
        """Upgrade a real pre-G2 database with an existing completed image job."""
        db_path = self.sink.volume_root / "legacy_jobs.sqlite"
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE image_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                asset_id TEXT, error TEXT)""")
            db.execute(
                "INSERT INTO image_jobs "
                "(id, owner, prompt, profile_id, params, state, created, updated, asset_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("legacy-completed", "owner-a", "old prompt", "test", "{}",
                 "completed", 1.0, 1.0, "legacy-image"),
            )
        upgraded = ImageJobStore(str(db_path))
        with sqlite3.connect(db_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(image_jobs)")}
            self.assertTrue({"claimed_by", "cancel_requested"} <= columns)
            self.assertEqual(
                [row[2] for row in db.execute(
                    "PRAGMA index_info(image_jobs_owner_asset_state)")],
                ["owner", "asset_id", "state"],
            )
        self.assertTrue(upgraded.owns_completed_asset("owner-a", "legacy-image"))
        self.assertFalse(upgraded.owns_completed_asset("owner-b", "legacy-image"))
        self.assertTrue(ImageJobStore(str(db_path)).owns_completed_asset(
            "owner-a", "legacy-image"
        ))

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_owner_guard_refuses_unmounted_volume_after_authorization(self, _mount):
        jobs = ImageJobStore(str(self.sink.volume_root / "jobs.sqlite"))
        asset_id = self.sink.publish(PNG, ".png")
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        self.assertEqual(jobs.claim()["id"], created["job_id"])
        self.assertTrue(jobs.finish(created["job_id"], asset_id=asset_id))
        self.assertEqual(read_owned_source_png(self.sink, jobs, "owner-a", asset_id), PNG)
        # Ownership in SQLite cannot override a missing/unverified media mount.
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(ArtifactSinkUnavailable):
                read_owned_source_png(self.sink, jobs, "owner-a", asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_public_volume_availability_requires_existing_mount(self, _mount):
        self.assertIsNone(self.sink.require_available())
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(ArtifactSinkUnavailable):
                self.sink.require_available()

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_wrong_bytes_and_bad_ids_refused(self, _mount):
        asset_id = self.sink.publish(b"not png", ".png")
        with self.assertRaises(SourceImageUnavailable):
            read_source_png(self.sink, asset_id)
        for bad in ("../secret", "", None, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                read_source_png(self.sink, bad)


if __name__ == "__main__":
    unittest.main()
