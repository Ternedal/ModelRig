"""Dormant DC-L08 Tier-A authority and verified-execution identity.

This stage can materialize authority, verify and stage signed runtime closures,
construct closure-bound plans and execute only through the private v3 module.
The authority surface itself exposes no process-launch function, final public
facade, trusted-Git, receipt, publisher, credential, remote or activation power.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import _tier_a_execution_core as _core
from .contract import DevelopmentTask

LEASE_SCHEMA = _core.LEASE_SCHEMA
PLAN_SCHEMA = "kaliv-development-tier-a-launch-plan/v3"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_OUTPUT_BYTES = 100_000_000
_ZERO_SHA256 = "0" * 64

TierAExecutionError = _core.TierAExecutionError
TierAExecutionLease = _core.TierAExecutionLease
LeasedCommandRegistry = _core.LeasedCommandRegistry
LeasedCatalogMaterializer = _core.LeasedCatalogMaterializer
TIER_A_APPLICATION_ENVIRONMENT = _core.TIER_A_APPLICATION_ENVIRONMENT
workspace_root_authority_sha256 = _core.workspace_root_authority_sha256

# Preserve the landed DC-L06 v1 compatibility exports. DC-L07's closure-bound
# v3 plan lives in ``tier_a_plan`` and is exported from the package root. These
# aliases keep earlier bounded tests and consumers working without exposing the
# private DC-L08 executor from this authority surface.
TierALaunchPlan = _core.TierALaunchPlan
build_tier_a_launch_plan = _core.build_tier_a_launch_plan

for _private_execution_name in (
    "_run_tier_a_launch_plan",
    "run_verified_tier_a_command",
):
    if hasattr(_core, _private_execution_name) or _private_execution_name in globals():
        raise TierAExecutionError(
            f"DC-L08 authority exposes private execution authority: "
            f"{_private_execution_name}"
        )
del _private_execution_name

# Exact source chain that can issue, transform or privately execute DC-L08
# runtime authority. The v6 domain excludes the final DC-L09 facade, command
# receipt, trusted-Git, publisher and remote-authority modules.
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
    "devcontrol/src/kaliv_dev_control/runtime_staging.py",
    "devcontrol/src/kaliv_dev_control/streaming_publication.py",
    "devcontrol/src/kaliv_dev_control/_runtime_closure_common.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_model.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_verify.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_staging.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_builder.py",
    "devcontrol/src/kaliv_dev_control/store.py",
    "devcontrol/src/kaliv_dev_control/tier_a_authority.py",
    "devcontrol/src/kaliv_dev_control/tier_a_plan.py",
    "devcontrol/src/kaliv_dev_control/tier_a_result.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_lease.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_environment.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_materialization.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _task_sha(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _is_linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if _is_linkish(current):
            return True
        if current.parent == current:
            return False
        current = current.parent


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _working_directory(root: Path, relative: str) -> Path:
    if relative == ".":
        candidate = root
    else:
        if not isinstance(relative, str):
            raise TierAExecutionError("Tier-A working directory is invalid")
        parsed = PurePosixPath(relative)
        if (
            relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise TierAExecutionError("Tier-A working directory is invalid")
        candidate = root.joinpath(*parsed.parts)
    if _has_linkish_component(candidate) or not candidate.is_dir():
        raise TierAExecutionError("Tier-A working directory is missing or unsafe")
    resolved = candidate.resolve()
    if not _inside(resolved, root):
        raise TierAExecutionError("Tier-A working directory escaped the workspace")
    return resolved


def working_directory_authority_sha256(root: Path, relative: str) -> str:
    """Bind a canonical workspace-relative cwd to its exact physical path."""

    canonical_root = _core._canonical_directory(root, name="workspace root")
    directory = _working_directory(canonical_root, relative)
    normalized = os.path.normcase(os.fspath(directory))
    return hashlib.sha256(
        b"kaliv-tier-a-working-directory/v1\0"
        + relative.encode("utf-8")
        + b"\0"
        + normalized.encode("utf-8", "surrogatepass")
    ).hexdigest()


def tier_a_toolhost_sha256(control_plane_root: Path) -> str:
    """Hash the complete private v6 DC-L08 verified-execution source chain."""

    root = _core._canonical_directory(
        control_plane_root,
        name="control-plane root",
    )
    digest = hashlib.sha256()
    digest.update(b"kaliv-tier-a-toolhost/v6\0")
    for relative in _TIER_A_BUNDLE_FILES:
        path = root / PurePosixPath(relative)
        if _has_linkish_component(path) or not path.is_file():
            raise TierAExecutionError(
                f"Tier-A toolhost bundle file is missing or unsafe: {relative}"
            )
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()
