"""Operator-only ComfyUI launch plan; no process is started by this module.

ComfyUI supports --input-directory, --output-directory, --temp-directory and
--user-directory. Model search paths must be configured and verified separately.
"""
from __future__ import annotations

import os
from pathlib import Path

from .video_comfy_storage_env import comfy_external_environment
from .video_storage_config import configured_video_storage


def build_comfy_launch_plan(python_executable: str, main_py: str,
                            environ: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    """Return argv/environment for a supervised, loopback-only ComfyUI process.

    Caller must verify external-volume identity and that the installed ComfyUI
    version honors these CLI options before executing the plan.
    """
    env = os.environ.copy() if environ is None else dict(environ)
    storage = configured_video_storage(env)
    py = Path(python_executable)
    main = Path(main_py)
    if not py.is_absolute() or not py.is_file():
        raise ValueError("Absolute existing Python executable required")
    if not main.is_absolute() or not main.is_file() or main.name != "main.py":
        raise ValueError("Absolute existing ComfyUI main.py required")
    user_dir = storage.root / "ComfyUI" / "user"
    # Check the parent too: ComfyUI -> another volume would redirect user data.
    if user_dir.parent.is_symlink() or user_dir.is_symlink():
        raise ValueError("ComfyUI user path or parent is a symlink")
    if not user_dir.is_dir():
        raise ValueError("ComfyUI user directory must be provisioned on external storage before launch")
    if not user_dir.resolve().is_relative_to(storage.root.resolve()):
        raise ValueError("ComfyUI user path escaped external root")
    paths = comfy_external_environment(env)
    argv = [
        str(py), str(main),
        "--listen", "127.0.0.1",
        "--port", "8188",
        "--input-directory", paths["COMFYUI_INPUT_DIRECTORY"],
        "--output-directory", paths["COMFYUI_OUTPUT_DIRECTORY"],
        "--temp-directory", paths["COMFYUI_TEMP_DIRECTORY"],
        "--user-directory", str(user_dir),
    ]
    env.update(paths)
    return argv, env
