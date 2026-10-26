"""Read-only image preflight tests; no CUDA or external drive required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.image_preflight import check_media, run_preflight
from app.image_media_store import MediaStorageError
from app.image_gpu_admission import GpuBudget


class ImagePreflightTests(unittest.TestCase):
    def test_rejects_regular_directory_not_mount(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.image_preflight.os.path.ismount", return_value=False):
                with self.assertRaises(MediaStorageError):
                    check_media(folder, folder, 0)

    def test_rejects_os_root_even_if_mounted(self):
        root = str(Path("/").resolve())
        with patch("app.image_preflight.os.path.ismount", return_value=True):
            with self.assertRaises(MediaStorageError):
                check_media(root, root, 0)

    def test_accepts_configured_mount(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.image_preflight.os.path.ismount", return_value=True):
                report = check_media(folder, folder, 0)
            self.assertEqual(report["media_root"], str(Path(folder).resolve()))

    def test_gpu_checked_only_after_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.image_preflight.os.path.ismount", return_value=False), patch(
                    "app.image_preflight.inspect_cuda_budget") as probe:
                with self.assertRaises(MediaStorageError):
                    run_preflight(1, folder, folder, 3, 6, 0)
                probe.assert_not_called()

    def test_report_gpu_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = GpuBudget(1, 12 * 1024**3, 10 * 1024**3, 3 * 1024**3, 7 * 1024**3)
            with patch("app.image_preflight.os.path.ismount", return_value=True), patch(
                    "app.image_preflight.inspect_cuda_budget", return_value=fake):
                report = run_preflight(1, folder, folder, 3, 6, 0)
            self.assertEqual(report["gpu"]["index"], 1)
            self.assertEqual(report["status"], "ready_for_model_qualification")


if __name__ == "__main__":
    unittest.main()
