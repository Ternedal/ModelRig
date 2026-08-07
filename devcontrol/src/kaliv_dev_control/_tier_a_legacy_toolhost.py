"""DC-L06 retained v2 Tier-A source-bundle identity.

The tuple is the exact stage-local authority closure. It contains no runtime
staging, executor, trusted-Git, receipt, reviewer, publisher or remote-authority
module from a later landing slice.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from ._tier_a_lease import TierAExecutionError
from ._tier_a_path_authority import _canonical_directory


_TIER_A_BUNDLE_FILES = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_capture.py",
    "worker/app/windows_runtime_guard.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/bounded_subprocess.py",
    "devcontrol/src/kaliv_dev_control/campaign.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/durable_publication.py",
    "devcontrol/src/kaliv_dev_control/evidence.py",
    "devcontrol/src/kaliv_dev_control/files.py",
    "devcontrol/src/kaliv_dev_control/github_read.py",
    "devcontrol/src/kaliv_dev_control/patch.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/policy.py",
    "devcontrol/src/kaliv_dev_control/proposal.py",
    "devcontrol/src/kaliv_dev_control/review.py",
    "devcontrol/src/kaliv_dev_control/store.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_lease.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_environment.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_materialization.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
    "devcontrol/src/kaliv_dev_control/tier_a_authority.py",
)


def tier_a_toolhost_sha256(control_plane_root: Path) -> str:
    """Hash the complete DC-L06 source chain that can shape Tier-A authority."""

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
