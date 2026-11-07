"""Offline media asset lookup and bounded byte-range tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_asset import open_asset, read_asset_range, iter_asset_chunks, stream_open_asset, GalleryAssetNotFound
from app.media_gallery_catalog import GalleryUnavailable
from app.media_gallery_range import RangeNotSatisfiable


class GalleryAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.volume = Path(self.tmp.name)
        self.root = self.volume / "media"
        self.root.mkdir()
        (self.root / "asset_1.mp4").write_bytes(b"0123456789")
        (self.root / "gallery-index.json").write_text(json.dumps([{
            "id": "asset_1", "kind": "video", "mime_type": "video/mp4",
            "size_bytes": 10, "created_at": "2026-10-29T07:00:00Z"
        }]), encoding="utf-8")

    def test_authenticated_adapter_can_read_single_range(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            handle, entry = open_asset(self.root, self.volume, "asset_1")
            with handle:
                data, status, headers = read_asset_range(handle, entry, "bytes=2-5")
            self.assertEqual((data, status), (b"2345", 206))
            self.assertEqual(headers["Content-Range"], "bytes 2-5/10")

    def test_range_refuses_truncation_during_read(self):
        import os
        target = self.root / "asset_1.mp4"
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            handle, entry = open_asset(self.root, self.volume, "asset_1")
            with handle:
                original_fstat = os.fstat
                calls = [0]

                def truncate_after_read(fd):
                    calls[0] += 1
                    if calls[0] == 2:
                        with open(target, "r+b") as writer:
                            writer.truncate(2)
                    return original_fstat(fd)

                with patch("app.media_gallery_asset.os.fstat", side_effect=truncate_after_read):
                    with self.assertRaisesRegex(GalleryUnavailable, "asset_changed_during_read"):
                        read_asset_range(handle, entry, "bytes=0-1")

    def test_range_refuses_same_size_in_place_rewrite(self):
        import os
        target = self.root / "asset_1.mp4"
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            handle, entry = open_asset(self.root, self.volume, "asset_1")
            with handle:
                original_fstat = os.fstat
                calls = [0]

                def rewrite_after_read(fd):
                    calls[0] += 1
                    if calls[0] == 2:
                        before = original_fstat(fd)
                        with open(target, "r+b") as writer:
                            writer.write(b"XXXXXXXXXX")
                        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
                    return original_fstat(fd)

                with patch("app.media_gallery_asset.os.fstat", side_effect=rewrite_after_read):
                    with self.assertRaisesRegex(GalleryUnavailable, "asset_changed_during_read"):
                        read_asset_range(handle, entry, "bytes=0-1")

    def test_full_stream_reads_in_bounded_chunks(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            handle, entry = open_asset(self.root, self.volume, "asset_1")
            with handle:
                self.assertEqual(list(iter_asset_chunks(handle, entry, chunk_size=3)),
                                 [b"012", b"345", b"678", b"9"])

    def test_stream_detects_truncated_file(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            handle, entry = open_asset(self.root, self.volume, "asset_1")
            with handle:
                (self.root / "asset_1.mp4").write_bytes(b"0")
                with self.assertRaisesRegex(GalleryUnavailable, "asset_changed_during_read"):
                    list(iter_asset_chunks(handle, entry, chunk_size=3))

    def test_stream_rejects_unbounded_chunk(self):
        with self.assertRaises(ValueError):
            list(iter_asset_chunks(None, {"size_bytes": 1}, chunk_size=2 * 1024 * 1024))

    def test_stream_owns_file_handle_and_closes_on_completion(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            stream = stream_open_asset(self.root, self.volume, "asset_1", chunk_size=4)
            self.assertEqual(b"".join(stream), b"0123456789")
            self.assertEqual(list(stream), [])

    def test_stream_rejects_invalid_chunk_before_open(self):
        with self.assertRaises(ValueError):
            stream_open_asset(self.root, self.volume, "asset_1", chunk_size=0)

    def test_missing_and_traversal_are_refused(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            for asset_id in ("../asset_1", "not_there", "asset_1\\Z", "asset_1\n"):
                with self.assertRaises(GalleryAssetNotFound):
                    open_asset(self.root, self.volume, asset_id)

    def test_asset_replaced_after_open_is_refused(self):
        import os
        original_lstat = os.lstat
        target = self.root / "asset_1.mp4"

        def changed_inode(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if os.fspath(path) == os.fspath(target):
                class Changed:
                    st_dev = info.st_dev
                    st_ino = info.st_ino + 1
                    st_mode = info.st_mode
                return Changed()
            return info

        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with patch("app.media_gallery_asset.os.lstat", side_effect=changed_inode):
                with self.assertRaisesRegex(GalleryUnavailable, "asset_changed_during_open"):
                    open_asset(self.root, self.volume, "asset_1")

    def test_symlink_is_refused(self):
        target = self.root / "asset_1.mp4"
        target.unlink()
        other = self.root / "elsewhere"
        other.write_bytes(b"0123456789")
        try:
            target.symlink_to(other)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            with self.assertRaises(GalleryUnavailable):
                open_asset(self.root, self.volume, "asset_1")


if __name__ == "__main__":
    unittest.main()
