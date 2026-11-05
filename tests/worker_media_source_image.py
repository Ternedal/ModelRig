"""Offline regressions for the read-only image source seam."""
import os
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
        with self.assertRaises(ArtifactSinkUnavailable):
            read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_completed_owner_guard_on_main_g2(self, _mount):
        jobs = ImageJobStore(str(self.sink.volume_root / "owner_guard.sqlite"))
        asset_id = self.sink.publish(PNG, ".png")
        created = jobs.submit("owner-a", "test prompt", profile_id="test")
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", asset_id)
        instance = "GPU-00000000-0000-0000-0000-000000000001:0123456789abcdef"
        self.assertEqual(jobs.claim_for(["test"], instance)["id"], created["job_id"])
        self.assertTrue(jobs.begin_publish(created["job_id"], instance))
        with self.assertRaises(SourceImageUnavailable):
            read_owned_source_png(self.sink, jobs, "owner-a", asset_id)
        self.assertTrue(jobs.complete(created["job_id"], instance, asset_id))
        self.assertEqual(read_owned_source_png(self.sink, jobs, "owner-a", asset_id), PNG)
        with patch.object(self.sink, "_root", side_effect=AssertionError(
            "unauthorized owner must not access gallery"
        )):
            with self.assertRaises(SourceImageUnavailable):
                read_owned_source_png(self.sink, jobs, "owner-b", asset_id)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(ArtifactSinkUnavailable):
                read_owned_source_png(self.sink, jobs, "owner-a", asset_id)

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
        with self.assertRaises(ArtifactSinkUnavailable):
            read_source_png(self.sink, asset_id)
        # Windows lacks O_NOFOLLOW; static symlinks must still fail closed.
        with patch.object(os, "O_NOFOLLOW", 0, create=True):
            with self.assertRaises(ArtifactSinkUnavailable):
                read_source_png(self.sink, asset_id)
        self.assertEqual(target.read_bytes(), PNG)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_corrupt_crc_and_truncated_png_refused(self, _mount):
        for bad in (PNG[:-5], PNG[:-12], PNG[:8] + b"junk", PNG[:-1] + bytes([PNG[-1] ^ 1])):
            with self.subTest(length=len(bad)):
                asset_id = self.sink.publish(bad, ".png")
                with self.assertRaises(ArtifactSinkUnavailable):
                    read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_oversized_dimensions_refused(self, _mount):
        oversized = (PNG[:8] + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 9000, 1, 8, 2, 0, 0, 0))
                     + PNG[33:])
        asset_id = self.sink.publish(oversized, ".png")
        with self.assertRaises(ArtifactSinkUnavailable):
            read_source_png(self.sink, asset_id)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_wrong_bytes_and_bad_ids_refused(self, _mount):
        asset_id = self.sink.publish(b"not png", ".png")
        with self.assertRaises(ArtifactSinkUnavailable):
            read_source_png(self.sink, asset_id)
        for bad in ("../secret", "", None, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                read_source_png(self.sink, bad)


if __name__ == "__main__":
    unittest.main()
