"""Bounded, opt-in ComfyUI directory environment configuration.

Produces environment variables for an operator-owned launcher. ComfyUI CLI
flags and custom-node caches still require deployment-specific verification.
"""
from __future__ import annotations

import os
from pathlib import Path

from .video_storage_config import configured_video_storage


def comfy_external_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return explicit paths for a supervised ComfyUI process.

    Never launch ComfyUI implicitly. Caller must check that the target ComfyUI
    version honors these settings; an env var alone is not a storage guarantee.
    """
    storage = configured_video_storage(environ)
    paths = storage.initialize_directories()
    root = storage.root
    comfy_root = root / "ComfyUI"
    dirs = {
        "COMFYUI_INPUT_DIRECTORY": comfy_root / "input",
        "COMFYUI_OUTPUT_DIRECTORY": comfy_root / "output",
        "COMFYUI_TEMP_DIRECTORY": comfy_root / "temp",
        "COMFYUI_MODEL_DIRECTORY": comfy_root / "models",
        "HF_HOME": comfy_root / "huggingface",
        "TORCH_HOME": comfy_root / "torch",
        "XDG_CACHE_HOME": comfy_root / "xdg-cache",
        "TMPDIR": paths["temp"],
        "TEMP": paths["temp"],
        "TMP": paths["temp"],
    }
    for path in dirs.values():
        if path.is_symlink():
            raise ValueError("ComfyUI path is a symlink")
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("ComfyUI path escaped approved media root")
    return {key: str(value) for key, value in dirs.items()}
