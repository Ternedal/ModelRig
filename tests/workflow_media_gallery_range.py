"""Offline bounded range parser regression tests."""
import unittest
from app.media_gallery_range import RangeNotSatisfiable, select_range


class MediaGalleryRangeTests(unittest.TestCase):
    def test_full_and_empty(self):
        self.assertEqual(select_range(None, 10), (0, 9, 200))
        self.assertEqual(select_range(None, 0), (0, -1, 200))

    def test_single_ranges(self):
        self.assertEqual(select_range("bytes=2-5", 10), (2, 5, 206))
        self.assertEqual(select_range("bytes=8-", 10), (8, 9, 206))
        self.assertEqual(select_range("bytes=-3", 10), (7, 9, 206))
        self.assertEqual(select_range("bytes=0-99", 10), (0, 9, 206))
        self.assertEqual(select_range("bytes=0-", 100, max_chunk=4), (0, 3, 206))

    def test_reject_unsupported_or_unsafe(self):
        for header in ("bytes=0-1,3-4", "items=0-1", "bytes=-0",
                       "bytes=-", "bytes=10-", "bytes=5-4",
                       "bytes=0-9", "bytes=-9", "bytes=+1-2",
                       "bytes=0-1\n"):
            with self.subTest(header=header), self.assertRaises(RangeNotSatisfiable):
                select_range(header, 10, max_chunk=4)

    def test_reject_unbounded_chunk_limit(self):
        for max_chunk in (0, -1, True, 1.5, 1 << 63):
            with self.subTest(max_chunk=max_chunk), self.assertRaises(ValueError):
                select_range("bytes=0-", 10, max_chunk=max_chunk)

    def test_reject_empty_asset_range(self):
        with self.assertRaises(RangeNotSatisfiable):
            select_range("bytes=0-0", 0)

    def test_reject_invalid_sizes(self):
        for size in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                select_range(None, size)


if __name__ == "__main__":
    unittest.main()
