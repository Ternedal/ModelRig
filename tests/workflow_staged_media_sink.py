"""Offline contract tests for the external-volume staged media sink."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.staged_media_sink import MediaStoreUnavailable, StagedFileArtifactSink


class StagedSinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def sink(self):
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            return StagedFileArtifactSink(self.root)

    def test_unmounted_refused(self):
        with self.assertRaises(MediaStoreUnavailable):
            StagedFileArtifactSink(self.root)

    def test_adopt_and_cleanup(self):
        sink = self.sink()
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            with sink.staged(".mp4") as path:
                path.write_bytes(b"fake-mp4")
                asset_id = sink.adopt(path, "video/mp4")
                self.assertEqual((self.root / (asset_id + ".mp4")).read_bytes(), b"fake-mp4")
            self.assertFalse(path.exists())

    def test_unadopted_staging_is_removed(self):
        sink = self.sink()
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            with sink.staged(".mp4") as path:
                path.write_bytes(b"partial")
            self.assertFalse(path.exists())

    def test_hardlink_refused(self):
        sink = self.sink()
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            with sink.staged(".mp4") as path:
                path.write_bytes(b"fake-mp4")
                other = self.root / "linked.mp4"
                other.hardlink_to(path)
                self.addCleanup(other.unlink)
                with self.assertRaises(MediaStoreUnavailable):
                    sink.adopt(path, "video/mp4")

    def test_symlinked_staging_directory_refused(self):
        sink = self.sink()
        staging = self.root / ".staging"
        staging.mkdir()
        staging.rmdir()
        target = self.root / "other"
        target.mkdir()
        staging.symlink_to(target, target_is_directory=True)
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            with self.assertRaises(MediaStoreUnavailable):
                with sink.staged(".mp4"):
                    pass

    def test_mime_and_outside_paths_refused(self):
        sink = self.sink()
        with patch("app.staged_media_sink.os.path.ismount", return_value=True):
            with sink.staged(".mp4") as path:
                path.write_bytes(b"fake-mp4")
                with self.assertRaises(MediaStoreUnavailable):
                    sink.adopt(path, "image/png")
            with self.assertRaises(MediaStoreUnavailable):
                sink.adopt(self.root / "other.mp4.part", "video/mp4")


if __name__ == "__main__":
    unittest.main()
