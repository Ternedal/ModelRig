"""Canonical Tier-A path and regular-file authority checks."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ._tier_a_lease import TierAExecutionError, _sha256


def _has_symlink_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _canonical_directory(path: Path, *, name: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise TierAExecutionError(f"{name} must be absolute")
    if _has_symlink_component(raw):
        raise TierAExecutionError(f"{name} must not contain symlinks")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise TierAExecutionError(f"{name} must be an existing directory")
    return resolved


def workspace_root_authority_sha256(path: Path) -> str:
    """Hash the exact canonical workspace path used by the physical campaign."""

    root = _canonical_directory(path, name="workspace root")
    canonical = os.path.normcase(os.fspath(root))
    return _sha256(
        b"kaliv-tier-a-workspace/v1\0"
        + canonical.encode("utf-8", "surrogatepass")
    )


def _regular_file_hash(path: Path, *, name: str) -> str:
    if not path.is_absolute() or _has_symlink_component(path) or not path.is_file():
        raise TierAExecutionError(
            f"{name} must be an absolute regular non-symlink file"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
