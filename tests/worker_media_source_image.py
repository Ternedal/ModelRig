"""Offline regressions for the read-only image source seam."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_store import ExternalMediaSink
from app.media_source_image import read_source_png
from app.media_generation_contract import ArtifactSinkUnavailable


PNG = b"\x89PNG\r\n\x1a\n" + b"fixture"


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
        self.assertEqual(target.read_bytes(), PNG)

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
