"""Dormant DC-L06 Tier-A authority identities and materialization surface.

This module exposes only identities that have landed by DC-L06. It deliberately
contains no process-launch, runtime-staging, trusted-Git, receipt, publication or
remote authority.
"""
from __future__ import annotations

from . import _tier_a_execution_core as _core

LEASE_SCHEMA = _core.LEASE_SCHEMA
PLAN_SCHEMA = _core.PLAN_SCHEMA
TierAExecutionError = _core.TierAExecutionError
TierAExecutionLease = _core.TierAExecutionLease
LeasedCommandRegistry = _core.LeasedCommandRegistry
LeasedCatalogMaterializer = _core.LeasedCatalogMaterializer
TierALaunchPlan = _core.TierALaunchPlan
build_tier_a_launch_plan = _core.build_tier_a_launch_plan
TIER_A_APPLICATION_ENVIRONMENT = _core.TIER_A_APPLICATION_ENVIRONMENT
workspace_root_authority_sha256 = _core.workspace_root_authority_sha256
tier_a_toolhost_sha256 = _core.tier_a_toolhost_sha256

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

if _TIER_A_BUNDLE_FILES != _core._TIER_A_BUNDLE_FILES:
    raise TierAExecutionError("DC-L06 Tier-A bundle projections disagree")
