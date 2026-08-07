"""Retained non-capturing Windows executor removed from the modern authority surface."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from ._tier_a_lease import TierAExecutionError
from ._tier_a_legacy_plan import TierALaunchPlan, build_tier_a_launch_plan
from ._tier_a_legacy_toolhost import tier_a_toolhost_sha256
from ._tier_a_materialization import LeasedCatalogMaterializer
from ._tier_a_path_authority import (
    _canonical_directory,
    _regular_file_hash,
    workspace_root_authority_sha256,
)
from .catalog import (
    IsolationAttestation,
    ModelRigCommandCatalog,
    Toolchain,
)
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier


def _run_tier_a_launch_plan(
    plan: TierALaunchPlan,
    *,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> int:
    """Execute a freshly verified internal plan through AppContainer + Job Object."""

    if not isinstance(plan, TierALaunchPlan):
        raise TierAExecutionError("Tier-A runtime requires a validated launch plan")
    if os.name != "nt":
        raise TierAExecutionError("Tier-A launch requires Windows")
    root = _canonical_directory(Path(plan.workspace_root), name="workspace root")
    if workspace_root_authority_sha256(root) != plan.workspace_root_sha256:
        raise TierAExecutionError("Tier-A workspace authority changed after planning")
    if tier_a_toolhost_sha256(control_plane_root) != plan.toolhost_sha256:
        raise TierAExecutionError("Tier-A authority code changed after planning")
    executable = Path(plan.argv[0]).resolve()
    if _regular_file_hash(
        executable, name="Tier-A executable"
    ) != plan.executable_sha256:
        raise TierAExecutionError("Tier-A executable changed after planning")

    try:
        from app.windows_job import (
            JobLimits,
            close_attached_job,
            terminate_attached_job,
        )
        from app.windows_restricted import (
            AppContainerProfile,
            RestrictedLaunchPolicy,
            provision_workspace_acl,
        )
        from app.windows_tier_a import spawn_tier_a_in_job
    except ImportError as exc:
        raise TierAExecutionError(
            "authoritative worker Tier-A modules are unavailable"
        ) from exc

    policy = RestrictedLaunchPolicy(os.fspath(root))
    profile = AppContainerProfile(policy)
    process = None
    try:
        receipt = provision_workspace_acl(policy, profile)
        process = spawn_tier_a_in_job(
            plan.argv,
            source_env=os.environ if source_env is None else source_env,
            application_env=plan.env,
            limits=JobLimits(
                process_memory_bytes=process_memory_bytes,
                active_process_limit=active_process_limit,
            ),
            policy=policy,
            profile=profile,
            acl_receipt=receipt,
        )
        try:
            return process.wait(timeout=plan.max_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            terminate_attached_job(process)
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            raise TierAExecutionError(
                "Tier-A command exceeded its fixed timeout"
            ) from exc
        finally:
            if process is not None:
                try:
                    close_attached_job(process)
                except Exception:
                    pass
                try:
                    process.close()
                except Exception:
                    pass
    finally:
        profile.delete()


def run_verified_tier_a_command(
    task: DevelopmentTask,
    catalog: ModelRigCommandCatalog,
    toolchain: Toolchain,
    attestation: IsolationAttestation,
    physical_verifier: WindowsPhysicalIsolationVerifier,
    command_id: str,
    *,
    trusted_runtime_root: Path,
    workspace_root: Path,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    executable_verifier: Any | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> int:
    """Reverify, stage one trusted runtime, build a fresh plan and launch it."""

    registry = LeasedCatalogMaterializer(
        catalog,
        physical_verifier,
        executable_verifier=executable_verifier,
    ).materialize(task, toolchain, attestation)

    # Import locally so package initialization does not create a circular import:
    # runtime_staging validates LeasedCommandRegistry from the compatibility core.
    # The module remains in the signed Tier-A bundle, so any change invalidates the
    # physical report before a lease can be issued.
    from .runtime_staging import TrustedRuntimeStager

    stager = TrustedRuntimeStager(trusted_runtime_root, workspace_root)
    staging_receipt = stager.stage(registry, task, command_id)
    staged_registry = stager.bind_for_launch(
        staging_receipt,
        registry,
        task,
        command_id,
    )
    plan = build_tier_a_launch_plan(
        staged_registry,
        task,
        command_id,
        workspace_root=workspace_root,
        control_plane_root=control_plane_root,
    )
    return _run_tier_a_launch_plan(
        plan,
        control_plane_root=control_plane_root,
        source_env=source_env,
        process_memory_bytes=process_memory_bytes,
        active_process_limit=active_process_limit,
    )
