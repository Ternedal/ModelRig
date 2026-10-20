"""Offline checks for the read-only video preflight."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_preflight import check, probe_nvidia_gpus
from app.video_storage import ExternalMediaStorage


class VideoPreflightTests(unittest.TestCase):
    def test_gpu_inventory_parses_two_independent_cards(self):
        from subprocess import CompletedProcess
        output = '0, NVIDIA GeForce RTX 3060, 12288\\n1, NVIDIA GeForce RTX 3060, 12288\\n'
        with patch('app.video_preflight.subprocess.run', return_value=CompletedProcess([], 0, output, '')):
            report = probe_nvidia_gpus()
        self.assertEqual(report['status'], 'detected')
        self.assertEqual([d['memory_mib'] for d in report['devices']], [12288, 12288])

    def test_gpu_inventory_times_out_safely(self):
        from subprocess import TimeoutExpired
        with patch('app.video_preflight.subprocess.run', side_effect=TimeoutExpired('nvidia-smi', 8)):
            self.assertEqual(probe_nvidia_gpus()['status'], 'unavailable')

    def test_missing_configuration_fails(self):
        report = check({})
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["storage"], "fail")

    def test_existing_root_passes_storage_but_not_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = ExternalMediaStorage(tmp, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "pass")
            self.assertFalse(report["ready"])
            self.assertTrue(report["limitations"])

    def test_symlinked_cache_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            try:
                (root / "Cache").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(str(exc))
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "fail")
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
