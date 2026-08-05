"""Retained v2 Tier-A source-bundle identity for the legacy launch path."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from ._tier_a_lease import TierAExecutionError
from ._tier_a_path_authority import _canonical_directory


# This tuple is deliberately retained byte-for-byte from the legacy core.
_TIER_A_BUNDLE_FILES = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/runtime_staging.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


def tier_a_toolhost_sha256(control_plane_root: Path) -> str:
    """Hash the retained source chain that can execute legacy Tier-A authority."""

    root = _canonical_directory(
        control_plane_root, name="control-plane root"
    )
    digest = hashlib.sha256()
    digest.update(b"kaliv-tier-a-toolhost/v2\0")
    for relative in _TIER_A_BUNDLE_FILES:
        path = root / PurePosixPath(relative)
        if path.is_symlink() or not path.is_file():
            raise TierAExecutionError(
                "Tier-A toolhost bundle file is missing or unsafe: "
                f"{relative}"
            )
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()
