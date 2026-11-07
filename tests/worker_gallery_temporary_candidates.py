"""Read-only stale-temp inventory; no automatic cleanup."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_store import ExternalMediaSink


class TemporaryCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        media = root / "media"
        media.mkdir()
        self.media = media
        self.sink = ExternalMediaSink(media, root)

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_only_old_regular_own_pattern_and_no_mutation(self, _mount):
        old = self.media / ".kaliv-abcdefgh.tmp"
        recent = self.media / ".kaliv-ijklmnop.tmp"
        unrelated = self.media / "notes.tmp"
        old.write_bytes(b"old")
        recent.write_bytes(b"new")
        unrelated.write_bytes(b"keep")
        then = time.time() - 7200
        os.utime(old, (then, then))
        report = self.sink.inspect_temporary_file_candidates(minimum_age_seconds=3600)
        self.assertEqual([item["name"] for item in report], [old.name])
        self.assertEqual(report[0]["size_bytes"], 3)
        self.assertEqual(report[0]["inode"], old.lstat().st_ino)
        self.assertTrue(all(path.exists() for path in (old, recent, unrelated)))

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_symlink_not_reported(self, _mount):
        target = self.media / "target"
        target.write_bytes(b"data")
        link = self.media / ".kaliv-abcdefgh.tmp"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(self.sink.inspect_temporary_file_candidates(minimum_age_seconds=60), [])
        self.assertTrue(link.is_symlink())

    @patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
    def test_age_validation(self, _mount):
        for value in (True, 0, 59, 30 * 86400 + 1, 1.5, "3600"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.sink.inspect_temporary_file_candidates(minimum_age_seconds=value)


if __name__ == "__main__":
    unittest.main()
