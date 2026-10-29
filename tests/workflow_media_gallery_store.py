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
