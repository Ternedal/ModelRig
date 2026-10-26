"""Offline tests for app playback byte-range behavior."""
import unittest

from app.video_media_ranges import UnsatisfiableRange, parse_single_range


class MediaRangeTests(unittest.TestCase):
    def test_full_file(self):
        self.assertIsNone(parse_single_range(None, 1000))

    def test_initial_chunk(self):
        result = parse_single_range("bytes=0-99", 1000)
        self.assertEqual((result.start, result.end, result.length), (0, 99, 100))
        self.assertEqual(result.content_range, "bytes 0-99/1000")

    def test_open_ended(self):
        result = parse_single_range("bytes=900-", 1000)
        self.assertEqual((result.start, result.end), (900, 999))

    def test_suffix(self):
        result = parse_single_range("bytes=-100", 1000)
        self.assertEqual((result.start, result.end), (900, 999))

    def test_clamped_end(self):
        result = parse_single_range("bytes=990-999999", 1000)
        self.assertEqual((result.start, result.end), (990, 999))

    def test_unsatisfiable(self):
        for value in ("bytes=1000-", "bytes=90-10", "bytes=0-1,3-4",
                      "items=0-5", "bytes=-0", "bytes=a-b", "bytes=-"):
            with self.subTest(value=value), self.assertRaises(UnsatisfiableRange):
                parse_single_range(value, 1000)

    def test_excessively_long_numeric_ranges_are_unsatisfiable(self):
        for header in ("bytes=" + "9" * 5000 + "-",
                       "bytes=-" + "9" * 5000,
                       "bytes=0-" + "9" * 5000):
            with self.subTest(length=len(header)), self.assertRaises(UnsatisfiableRange):
                parse_single_range(header, 1000)

    def test_empty_file(self):
        with self.assertRaises(UnsatisfiableRange):
            parse_single_range("bytes=0-", 0)


if __name__ == "__main__":
    unittest.main()
