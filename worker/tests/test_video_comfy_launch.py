"""Offline tests for external-only ComfyUI launch arguments."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_comfy_launch import build_comfy_launch_plan
from app.video_storage import ExternalMediaStorage


class ComfyLaunchTests(unittest.TestCase):
    def test_launch_plan_routes_large_dirs_to_media_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            py = root / "python.exe"
            main = root / "main.py"
            py.touch()
            main.touch()
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ):
                argv, env = build_comfy_launch_plan(str(py), str(main), {})
            self.assertEqual(argv[argv.index("--listen") + 1], "127.0.0.1")
            for flag in ("--input-directory", "--output-directory", "--temp-directory", "--user-directory"):
                self.assertTrue(Path(argv[argv.index(flag) + 1]).is_relative_to(root))
            for name in ("HF_HOME", "TORCH_HOME", "TMPDIR", "TEMP", "TMP"):
                self.assertTrue(Path(env[name]).is_relative_to(root))

    def test_rejects_missing_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.py"
            main.touch()
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ):
                with self.assertRaises(ValueError):
                    build_comfy_launch_plan(str(root / "missing.exe"), str(main), {})


if __name__ == "__main__":
    unittest.main()
