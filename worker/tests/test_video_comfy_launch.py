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
            (root / "ComfyUI" / "user").mkdir(parents=True)
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ):
                argv, env = build_comfy_launch_plan(str(py), str(main), {})
            self.assertEqual(argv[argv.index("--listen") + 1], "127.0.0.1")
            for flag in ("--input-directory", "--output-directory", "--temp-directory", "--user-directory"):
                self.assertTrue(Path(argv[argv.index(flag) + 1]).resolve().is_relative_to(root.resolve()))
            for name in ("HF_HOME", "TORCH_HOME", "TMPDIR", "TEMP", "TMP"):
                self.assertTrue(Path(env[name]).resolve().is_relative_to(root.resolve()))

    def test_missing_user_directory_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            py, main = root / "python.exe", root / "main.py"
            py.touch()
            main.touch()
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ):
                with self.assertRaisesRegex(ValueError, "must be provisioned"):
                    build_comfy_launch_plan(str(py), str(main), {})
            self.assertFalse((root / "ComfyUI").exists())

    def test_rejects_symlinked_comfy_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "external"
            root.mkdir()
            other = Path(tmp) / "other"
            other.mkdir()
            py = root / "python.exe"
            main = root / "main.py"
            py.touch()
            main.touch()
            try:
                (root / "ComfyUI").symlink_to(other, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    build_comfy_launch_plan(str(py), str(main), {})
            self.assertFalse((other / "user").exists())

    def test_launch_plan_rejects_missing_user_dir_without_provisioning_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            py, main = root / "python.exe", root / "main.py"
            py.touch()
            main.touch()
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_launch.configured_video_storage", return_value=storage), patch(
                "app.video_comfy_storage_env.configured_video_storage", return_value=storage
            ), patch("app.video_comfy_launch.comfy_external_environment") as provision:
                with self.assertRaisesRegex(ValueError, "must be provisioned"):
                    build_comfy_launch_plan(str(py), str(main), {})
            provision.assert_not_called()
            self.assertFalse((root / "ComfyUI").exists())

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
