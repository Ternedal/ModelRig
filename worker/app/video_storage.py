"""Fail-closed external media storage policy for generated assets.

Only validates and allocates paths; no automatic fallback to internal storage.
Caller must provide an operator-approved external mount/volume and configure
ComfyUI's model, input, output and temporary directories separately.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


class MediaStorageUnavailable(RuntimeError):
    pass


class ExternalMediaStorage:
    def __init__(self, root: str | Path, *, minimum_free_gb: int = 20):
        if not isinstance(root, (str, Path)) or not str(root).strip():
            raise ValueError("External media root is required")
        if type(minimum_free_gb) is not int or minimum_free_gb < 1:
            raise ValueError("Invalid free space reserve")
        self.root = Path(root).expanduser().resolve(strict=True)
        self.minimum_free_bytes = minimum_free_gb * 1024 ** 3
        if not self.root.is_dir():
            raise MediaStorageUnavailable("Media root is not a directory")

    def assert_ready(self) -> None:
        if not self.root.is_dir() or not os.access(self.root, os.W_OK):
            raise MediaStorageUnavailable("Configured media volume unavailable or read-only")
        # External-volume identity MUST be checked by deployment provisioning.
        # A bare directory on C: is not proof of an external drive.
        if shutil.disk_usage(self.root).free < self.minimum_free_bytes:
            raise MediaStorageUnavailable("Insufficient media volume free space")

    def initialize_directories(self) -> dict[str, Path]:
        self.assert_ready()
        paths = {
            "images": self.root / "Media" / "Images",
            "videos": self.root / "Media" / "Videos",
            "vr": self.root / "Media" / "VR",
            "jobs": self.root / "Jobs",
            "temp": self.root / "Temp",
            "cache": self.root / "Cache",
        }
        for path in paths.values():
            # Reject symlinks in every existing component, including Media itself.
            # Checking only the leaf misses Media -> another volume.
            for component in (path.parent, path):
                if component.is_symlink():
                    raise MediaStorageUnavailable("Symlinked media directory forbidden")
            path.mkdir(parents=True, exist_ok=True)
            if not path.resolve().is_relative_to(self.root):
                raise MediaStorageUnavailable("Media path escaped configured root")
        return paths
