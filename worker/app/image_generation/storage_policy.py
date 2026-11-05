"""Fail-closed external-drive selection for experimental image artifacts.

The operator must explicitly supply both the media root and the known mounted
volume root. This validates path containment, not hardware identity: platform
mount verification remains the responsibility of the host deployment.
"""
from __future__ import annotations

from pathlib import Path


def require_external_media_root(
    configured_root: str | Path | None,
    *,
    mounted_volume: str | Path | None,
) -> Path:
    if not configured_root or not mounted_volume:
        raise ValueError("Explicit external media root and mounted volume required")
    root = Path(configured_root).expanduser()
    volume = Path(mounted_volume).expanduser()
    if not root.is_absolute() or not volume.is_absolute():
        raise ValueError("Media paths must be absolute")
    if not volume.is_dir() or volume.is_symlink():
        raise ValueError("External media volume is unavailable")
    # Reject roots that traverse existing symlinks into a different filesystem.
    resolved_volume = volume.resolve(strict=True)
    if not root.is_relative_to(volume) or root == volume:
        raise ValueError("Media root must be beneath the configured external volume")
    if root.exists() and root.is_symlink():
        raise ValueError("Media root cannot be a symlink")
    # Resolve parent symlinks and reject paths redirected outside the volume.
    resolved_root = root.resolve(strict=False)
    if not resolved_root.is_relative_to(resolved_volume) or resolved_root == resolved_volume:
        raise ValueError("Media root escapes configured external volume")
    return resolved_root
