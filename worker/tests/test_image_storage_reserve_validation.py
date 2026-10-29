"""Additional strict configuration regression tests for image media storage."""
import tempfile
import unittest
from unittest.mock import patch

from app.image_media_store import ExternalMediaStore


class ImageStorageReserveValidationTests(unittest.TestCase):
    def test_invalid_free_space_reserve_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.image_media_store.os.path.ismount", return_value=True):
                for value in (None, True, False, 1.5, "100", [], {}, -1):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        ExternalMediaStore(directory, [directory], min_free_bytes=value)


if __name__ == "__main__":
    unittest.main()
