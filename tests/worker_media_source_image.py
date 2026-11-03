"""Offline regressions for the read-only image source seam."""
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_store import ExternalMediaSink
from app.media_source_image import read_source_png
from app.media_generation_contract import ArtifactSinkUnavailable


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
                with self.assertRaises(ArtifactSinkUnavailable):
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
