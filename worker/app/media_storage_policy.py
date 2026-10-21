"""Fail-closed media storage path policy for generated images and video.

This module is intentionally independent of generation engines and HTTP routes.
Call validate_media_root before creating any output directories.
"""
from __future__ import annotations

import os
from pathlib import Path


class MediaStorageError(ValueError):
    """Media storage is not safely configured."""


def validate_media_root(configured: str | None, *, system_drive: str | None = None) -> Path:
    """Return an existing, writable, non-system media directory.

    The caller must explicitly configure a path. On Windows, reject the system
    drive (normally C:), including paths through junctions/symlinks. On POSIX,
    require a mounted filesystem distinct from the filesystem holding /.
    This is conservative: no automatic fallback to internal storage.
    """
    if not isinstance(configured, str) or not configured.strip():
        raise MediaStorageError("External media root must be configured")
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute() or not candidate.exists() or not candidate.is_dir():
        raise MediaStorageError("Media root must be an existing absolute directory")
    resolved = candidate.resolve(strict=True)
    if os.name == "nt":
        drive = (system_drive or os.environ.get("SystemDrive") or "C:").upper().rstrip("\\")
        if resolved.drive.upper().rstrip("\\") == drive:
            raise MediaStorageError("System drive is forbidden for generated media")
    else:
        if os.stat(resolved).st_dev == os.stat("/").st_dev:
            raise MediaStorageError("Media root must be on a separate mounted filesystem")
    if not os.access(resolved, os.W_OK | os.X_OK):
        raise MediaStorageError("Media root is not writable")
    return resolved


def safe_media_target(root: Path, filename: str) -> Path:
    """Resolve a single generated filename without traversal or symlink escape."""
    if not isinstance(filename, str) or not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise MediaStorageError("Invalid media filename")
    target = root / filename
    if target.is_symlink() or target.exists():
        raise MediaStorageError("Media filename already exists")
    if target.parent.resolve(strict=True) != root.resolve(strict=True):
        raise MediaStorageError("Media target escapes configured root")
    return target


def write_media_exclusive(root: Path, filename: str, payload: bytes, *, max_bytes: int = 100_000_000) -> Path:
    """Exclusively create a media file without following an existing symlink.

    Caller must validate the external root at admission time. Revalidate here
    to fail closed if the mount disappears before writing.
    """
    root = validate_media_root(str(root))
    if not isinstance(max_bytes, int) or max_bytes < 1 or not isinstance(payload, bytes) or not payload or len(payload) > max_bytes:
        raise MediaStorageError("Invalid media payload size")
    target = safe_media_target(root, filename)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
