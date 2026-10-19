"""Fail-closed media root configuration for experimental video generation.

No default path: a deployment must explicitly select the external media volume.
Never create a directory under the worker repository or OS temp as a fallback.
"""
from __future__ import annotations

import os
from pathlib import Path

from .video_storage import ExternalMediaStorage, MediaStorageUnavailable


def configured_video_storage(environ: dict[str, str] | None = None) -> ExternalMediaStorage:
    env = os.environ if environ is None else environ
    raw = env.get("KALIV_MEDIA_ROOT", "").strip()
    if not raw:
        raise MediaStorageUnavailable("KALIV_MEDIA_ROOT is required; no internal fallback")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise MediaStorageUnavailable("KALIV_MEDIA_ROOT must be absolute")
    # Explicitly reject the system drive on Windows. External USB HDDs often
    # report DRIVE_FIXED, so OS drive type alone cannot prove external storage.
    if os.name == "nt":
        system_drive = env.get("SystemDrive", "C:").rstrip("\\/").casefold()
        if root.drive.casefold() == system_drive:
            raise MediaStorageUnavailable("System drive forbidden for media storage")
    try:
        reserve = int(env.get("KALIV_MEDIA_MIN_FREE_GB", "20"))
    except ValueError as exc:
        raise MediaStorageUnavailable("Invalid free-space reserve") from exc
    if not root.is_dir():
        raise MediaStorageUnavailable("Configured media volume not mounted")
    storage = ExternalMediaStorage(root, minimum_free_gb=reserve)
    storage.assert_ready()
    return storage
