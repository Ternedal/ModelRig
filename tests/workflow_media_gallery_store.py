"""Offline external media sink contract tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_store import ExternalMediaSink
from app.media_generation_contract import ArtifactSinkUnavailable


class ExternalMediaSinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.volume = Path(self.temp.name)
        self.media = self.volume / "media"
        self.media.mkdir()
        self.sink = ExternalMediaSink(self.media, self.volume)

    def test_publish_only_to_verified_volume(self):
        with patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: p == self.volume):
            asset = self.sink.publish(b"png-bytes", ".png")
        self.assertEqual((self.media / (asset + ".png")).read_bytes(), b"png-bytes")
        self.assertEqual(list(self.media.glob(".kaliv-*")), [])

    def test_job_publication_retries_same_asset(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            first = self.sink.publish_for_job("job_42", b"same-payload", ".png")
            second = self.sink.publish_for_job("job_42", b"same-payload", ".png")
        self.assertEqual(first, second)
        self.assertEqual((self.media / (first + ".png")).read_bytes(), b"same-payload")
        self.assertEqual(len(list(self.media.glob("*.png"))), 1)

    def test_job_publication_refuses_conflicting_content(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            asset = self.sink.publish_for_job("job_42", b"original", ".png")
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
                self.sink.publish_for_job("job_42", b"changed!", ".png")
        self.assertEqual((self.media / (asset + ".png")).read_bytes(), b"original")

    def test_job_publication_rejects_unsafe_key(self):
        with self.assertRaisesRegex(ValueError, "invalid_job_key"):
            self.sink.publish_for_job("../escape", b"data", ".png")

    def test_existing_asset_is_never_overwritten(self):
        asset = "f" * 32
        existing = self.media / (asset + ".png")
        existing.write_bytes(b"original")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
             patch("app.media_gallery_store.secrets.token_hex", return_value=asset):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_collision"):
                self.sink.publish(b"replacement", ".png")
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertEqual(list(self.media.glob(".kaliv-*")), [])

    def test_temp_cleanup_failure_after_publish_does_not_report_failed_job(self):
        original_unlink = Path.unlink
        def fail_temp_only(path, *args, **kwargs):
            if path.name.startswith(".kaliv-"):
                raise OSError("simulated cleanup failure")
            return original_unlink(path, *args, **kwargs)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
             patch.object(Path, "unlink", autospec=True, side_effect=fail_temp_only):
            asset = self.sink.publish(b"data", ".png")
        self.assertEqual((self.media / (asset + ".png")).read_bytes(), b"data")

    def test_publish_failure_cleans_temporary_file(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
             patch("app.media_gallery_store.os.link", side_effect=OSError("simulated link failure")):
            with self.assertRaises(ArtifactSinkUnavailable):
                self.sink.publish(b"data", ".png")
        self.assertEqual(list(self.media.iterdir()), [])

    def test_refuse_unmounted_volume_without_writing(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            with self.assertRaises(ArtifactSinkUnavailable):
                self.sink.publish(b"bytes", ".png")
        self.assertEqual(list(self.media.iterdir()), [])

    def test_refuse_unsafe_extension_and_empty_artifact(self):
        with self.assertRaises(ValueError):
            self.sink.publish(b"data", "../escape")
        with self.assertRaises(ValueError):
            self.sink.publish(b"", ".png")

    def test_refuse_missing_media_directory_without_creating_it(self):
        missing = self.volume / "missing"
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaises(ArtifactSinkUnavailable):
                ExternalMediaSink(missing, self.volume).publish(b"data", ".png")
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
