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
        output = '0, NVIDIA GeForce RTX 3060, 12288\n1, NVIDIA GeForce RTX 3060, 12288\n'
        with patch('app.video_preflight.subprocess.run', return_value=CompletedProcess([], 0, output, '')):
            report = probe_nvidia_gpus()
        self.assertEqual(report['status'], 'detected')
        self.assertEqual([d['memory_mib'] for d in report['devices']], [12288, 12288])

    def test_gpu_inventory_times_out_safely(self):
        from subprocess import TimeoutExpired
        with patch('app.video_preflight.subprocess.run', side_effect=TimeoutExpired('nvidia-smi', 8)):
            self.assertEqual(probe_nvidia_gpus()['status'], 'unavailable')

    def test_workflow_template_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "media"
            root.mkdir()
            outside = base / "workflow.json"
            outside.write_text("{}", encoding="utf-8")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({"KALIV_COMFY_WORKFLOW_TEMPLATE": str(outside)})
            self.assertEqual(report["checks"]["workflow_template"], "invalid")
            self.assertFalse(report["ready"])

    def test_preflight_accepts_canonical_root_with_alias_path(self):
        # Windows temp paths can have 8.3 and long-name aliases for the same directory.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / "workflow.json"
            workflow.write_text("{}", encoding="utf-8")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage), \
                 patch("app.video_preflight.trusted_text_to_video_factory", return_value=lambda _: {}), \
                 patch("app.video_preflight.probe_nodes", return_value={"status": "compatible"}):
                report = check({"KALIV_COMFY_WORKFLOW_TEMPLATE": str(workflow)})
            self.assertEqual(report["checks"]["storage"], "pass")
            self.assertEqual(report["checks"]["workflow_template"], "valid_structure")

    def test_missing_workflow_template_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = ExternalMediaStorage(tmp, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["workflow_template"], "not_configured")

    def test_cli_fails_when_only_storage_passes(self):
        import contextlib
        import io
        from app.video_preflight import main
        with patch("app.video_preflight.check", return_value={
            "ready": False,
            "checks": {"storage": "pass", "workflow_template": "not_configured",
                       "gpus": {"status": "detected"}},
            "limitations": [],
        }), patch("sys.argv", ["video_preflight"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)

    def test_cli_reports_diagnostics_pass_without_claiming_ready(self):
        import contextlib
        import io
        from app.video_preflight import main
        with patch("app.video_preflight.check", return_value={
            "ready": False,
            "checks": {"storage": "pass", "workflow_template": "valid_structure",
                       "comfy_nodes": {"status": "compatible"},
                       "gpus": {"status": "detected"}},
            "limitations": ["Physical drive not attested"],
        }), patch("sys.argv", ["video_preflight"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)

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

    def test_read_only_preflight_does_not_provision_media_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "pass")
            for name in ("Media", "Jobs", "Temp", "Cache", "ComfyUI"):
                with self.subTest(name=name):
                    self.assertFalse((root / name).exists())
            self.assertFalse(report["ready"])

    def test_nested_comfy_symlink_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            try:
                (root / "ComfyUI").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(str(exc))
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_preflight.configured_video_storage", return_value=storage):
                report = check({})
            self.assertEqual(report["checks"]["storage"], "fail")
            self.assertFalse(report["ready"])
            self.assertEqual(list(outside.iterdir()), [])

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
