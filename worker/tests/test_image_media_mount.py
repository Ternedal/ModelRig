"""Production image mount must stay inert unless explicitly configured."""
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.image_media_mount import mount_image_media


class ImageMediaMountTests(unittest.TestCase):
    def test_disabled_mount_registers_nothing(self):
        app = FastAPI()
        before = len(app.routes)
        with patch.dict(os.environ, {"KALIV_IMAGE_MEDIA_PILOT": "0"}, clear=False):
            self.assertFalse(mount_image_media(app))
        self.assertEqual(len(app.routes), before)

    def test_enabled_mount_requires_external_volume_configuration(self):
        app = FastAPI()
        before = len(app.routes)
        with patch.dict(os.environ, {"KALIV_IMAGE_MEDIA_PILOT": "1",
                                    "KALIV_IMAGE_INTERNAL_SECRET": "x" * 32,
                                    "KALIV_IMAGE_MEDIA_ROOT": "",
                                    "KALIV_IMAGE_EXTERNAL_MOUNT": "",
                                    "KALIV_IMAGE_JOBS_DB": ""}, clear=False):
            with self.assertRaises(RuntimeError):
                mount_image_media(app)
        self.assertEqual(len(app.routes), before)


if __name__ == "__main__":
    unittest.main()
