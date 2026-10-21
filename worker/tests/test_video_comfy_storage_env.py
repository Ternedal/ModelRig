"""Ensure cache provisioning cannot follow a symlinked ComfyUI parent."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_comfy_storage_env import comfy_external_environment
from app.video_storage import ExternalMediaStorage


class ComfyStorageEnvironmentTests(unittest.TestCase):
    def test_rejects_symlinked_temp_before_creating_comfy_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "external"
            root.mkdir()
            other = base / "other"
            other.mkdir()
            try:
                (root / "Temp").symlink_to(other, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_storage_env.configured_video_storage", return_value=storage):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    comfy_external_environment({})
            self.assertFalse((root / "ComfyUI").exists())
            self.assertEqual(list(other.iterdir()), [])

    def test_rejects_symlinked_parent_without_writing_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "external"
            root.mkdir()
            other = base / "other"
            other.mkdir()
            try:
                (root / "ComfyUI").symlink_to(other, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            storage = ExternalMediaStorage(root, minimum_free_gb=1)
            with patch("app.video_comfy_storage_env.configured_video_storage", return_value=storage):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    comfy_external_environment({})
            self.assertEqual(list(other.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
