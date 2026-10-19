"""Offline tests for streaming plans and bounded file reads."""
import tempfile
import unittest
from pathlib import Path

from app.video_media_stream import iter_media_bytes, media_response_plan


class MediaStreamTests(unittest.TestCase):
    def test_full_response(self):
        status, headers, start, length = media_response_plan(
            size=1000, mime_type="video/mp4"
        )
        self.assertEqual((status, start, length), (200, 0, 1000))
        self.assertEqual(headers["Content-Length"], "1000")

    def test_seek_response(self):
        status, headers, start, length = media_response_plan(
            size=1000, mime_type="video/mp4", range_header="bytes=100-199"
        )
        self.assertEqual((status, start, length), (206, 100, 100))
        self.assertEqual(headers["Content-Range"], "bytes 100-199/1000")

    def test_unsatisfiable_response(self):
        status, headers, _, length = media_response_plan(
            size=100, mime_type="video/mp4", range_header="bytes=200-"
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], "bytes */100")
        self.assertEqual(length, 0)

    def test_head_metadata(self):
        status, headers, _, length = media_response_plan(
            size=123, mime_type="image/png", method="HEAD"
        )
        self.assertEqual(status, 200)
        self.assertEqual(length, 123)
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_chunked_file_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.mp4"
            path.write_bytes(b"0123456789")
            self.assertEqual(
                b"".join(iter_media_bytes(path, 3, 4, chunk_size=2)), b"3456"
            )


if __name__ == "__main__":
    unittest.main()
