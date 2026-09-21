"""Shared non-executing Tier-A substrate verification for exact-task pilots.

This internal helper contains the physical-isolation, runtime-closure, trusted-Git,
workspace and toolhost verification that was originally embedded in ADR-DC-036.
It deliberately grants no authority and creates no receipt. Callers remain
responsible for proving their own upstream authority and for defining the exact
receipt semantics they expose.

The helper never launches the reviewed task, never invokes TrustedGitRunner.run
or evidence(), performs no network I/O and writes no durable state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from ._tier_a_environment import TIER_A_APPLICATION_ENVIRONMENT
from ._tier_a_materialization import LeasedCatalogMaterializer, LeasedCommandRegistry
from .catalog import IsolationAttestation, ModelRigCommandCatalog, Toolchain
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_model import SignedRuntimeClosureManifest
from .runtime_closure_verify import RuntimeClosureVerifier
from .tier_a_authority import tier_a_toolhost_sha256, workspace_root_authority_sha256
from .trusted_git_runtime_runner import TrustedGitRunner


class PilotExactTaskTierASubstrateError(ValueError):
    """The reviewed Tier-A substrate could not be verified without execution."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task_sha256(task: DevelopmentTask) -> str:
    if type(task) is not DevelopmentTask:
        raise PilotExactTaskTierASubstrateError("exact DevelopmentTask is required")
    return _sha256_text(task.canonical_json())


def _attestation_sha256(attestation: IsolationAttestation) -> str:
    if type(attestation) is not IsolationAttestation:
        raise PilotExactTaskTierASubstrateError(
            "exact IsolationAttestation is required"
        )
    return _sha256_text(attestation.canonical_json())


def source_environment_sha256() -> str:
    return _sha256_text(
        _canonical(dict(sorted(TIER_A_APPLICATION_ENVIRONMENT.items())))
    )


def materialize_verified_tier_a_substrate(
    *,
    task: DevelopmentTask,
    fixed_command_id: str,
    workspace_root_path_sha256: str,
    catalog: ModelRigCommandCatalog,
    toolchain: Toolchain,
    isolation_attestation: IsolationAttestation,
    physical_verifier: WindowsPhysicalIsolationVerifier,
    signed_runtime_closure: SignedRuntimeClosureManifest,
    runtime_closure_verifier: RuntimeClosureVerifier,
    trusted_runtime_root: Path,
    git_runner: TrustedGitRunner,
    workspace_root: Path,
    control_plane_root: Path,
    path_sha256: Callable[[Path], str],
) -> Mapping[str, Any]:
    """Verify and snapshot the exact reviewed Tier-A substrate without execution."""
    if type(task) is not DevelopmentTask:
        raise PilotExactTaskTierASubstrateError("exact DevelopmentTask is required")
    task_snapshot = DevelopmentTask.from_mapping(task.to_dict())
    if (
        task_snapshot != task
        or task_snapshot.allowed_command_ids != (fixed_command_id,)
        or task_snapshot.required_tests != task_snapshot.allowed_command_ids
    ):
        raise PilotExactTaskTierASubstrateError(
            "DevelopmentTask is not bound to exactly one fixed command"
        )

    if type(catalog) is not ModelRigCommandCatalog:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires an exact reviewed ModelRigCommandCatalog"
        )
    catalog_snapshot = catalog.snapshot()
    if catalog_snapshot.command_ids != (fixed_command_id,):
        raise PilotExactTaskTierASubstrateError(
            "executor catalog must contain exactly the bound fixed command"
        )

    if type(toolchain) is not Toolchain:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires an exact Toolchain"
        )
    toolchain_snapshot = toolchain.snapshot()
    specification = catalog_snapshot.resolve(fixed_command_id)
    toolchain_snapshot.resolve(specification.tool_id)

    if type(isolation_attestation) is not IsolationAttestation:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires the exact host-resolved isolation attestation"
        )
    attestation_snapshot = IsolationAttestation.from_mapping(
        isolation_attestation.to_dict()
    )
    if type(physical_verifier) is not WindowsPhysicalIsolationVerifier:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires the fixed Windows physical verifier"
        )
    try:
        leased = LeasedCatalogMaterializer(
            catalog_snapshot,
            physical_verifier,
        ).materialize(task_snapshot, toolchain_snapshot, attestation_snapshot)
    except Exception as exc:
        raise PilotExactTaskTierASubstrateError(
            "exact Tier-A physical lease materialization failed"
        ) from exc
    if type(leased) is not LeasedCommandRegistry:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A materializer returned an invalid leased registry"
        )

    if type(signed_runtime_closure) is not SignedRuntimeClosureManifest:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires one exact signed runtime closure"
        )
    signed_closure_snapshot = SignedRuntimeClosureManifest.from_mapping(
        signed_runtime_closure.to_dict()
    )
    if type(runtime_closure_verifier) is not RuntimeClosureVerifier:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires the fixed runtime-closure verifier"
        )
    try:
        verified_runtime_root, _ = runtime_closure_verifier.verify(
            signed_closure_snapshot,
            leased,
            task_snapshot,
            fixed_command_id,
            trusted_runtime_root=Path(trusted_runtime_root),
        )
    except Exception as exc:
        raise PilotExactTaskTierASubstrateError(
            "signed runtime closure verification failed"
        ) from exc

    raw_workspace = Path(workspace_root)
    if not raw_workspace.is_absolute() or raw_workspace.resolve() != raw_workspace:
        raise PilotExactTaskTierASubstrateError(
            "workspace root must be an exact canonical absolute path"
        )
    try:
        workspace_path_sha = path_sha256(raw_workspace)
    except Exception as exc:
        raise PilotExactTaskTierASubstrateError(
            "workspace path identity could not be verified"
        ) from exc
    if workspace_path_sha != workspace_root_path_sha256:
        raise PilotExactTaskTierASubstrateError(
            "workspace root path does not match the signed pilot scope"
        )
    workspace_authority_sha = workspace_root_authority_sha256(raw_workspace)
    if leased.lease.workspace_root_sha256 != workspace_authority_sha:
        raise PilotExactTaskTierASubstrateError(
            "physical execution lease does not name the exact workspace"
        )

    if type(git_runner) is not TrustedGitRunner:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A substrate requires the host-pinned TrustedGitRunner"
        )
    try:
        git_runner.runtime.verify()
    except Exception as exc:
        raise PilotExactTaskTierASubstrateError(
            "staged trusted Git runtime verification failed"
        ) from exc
    git_receipt = git_runner.runtime.receipt
    raw_operation_root = Path(git_runner.operation_root)
    if (
        not raw_operation_root.is_absolute()
        or raw_operation_root.resolve() != raw_operation_root
    ):
        raise PilotExactTaskTierASubstrateError(
            "trusted Git operation root is not canonical"
        )

    raw_control_plane = Path(control_plane_root)
    if (
        not raw_control_plane.is_absolute()
        or raw_control_plane.resolve() != raw_control_plane
    ):
        raise PilotExactTaskTierASubstrateError(
            "control-plane root must be an exact canonical absolute path"
        )
    try:
        toolhost_sha = tier_a_toolhost_sha256(raw_control_plane)
    except Exception as exc:
        raise PilotExactTaskTierASubstrateError(
            "Tier-A toolhost identity could not be verified"
        ) from exc
    if leased.lease.toolhost_sha256 != toolhost_sha:
        raise PilotExactTaskTierASubstrateError(
            "physical execution lease does not name the exact Tier-A toolhost"
        )

    manifest = signed_closure_snapshot.manifest
    if (
        manifest.task_id != task_snapshot.task_id
        or manifest.task_sha256 != _task_sha256(task_snapshot)
        or manifest.command_id != fixed_command_id
        or manifest.catalog_sha256 != catalog_snapshot.sha256
        or manifest.toolchain_sha256 != toolchain_snapshot.sha256
        or manifest.lease_sha256 != leased.lease.sha256
        or manifest.workspace_root_sha256 != workspace_authority_sha
    ):
        raise PilotExactTaskTierASubstrateError(
            "runtime closure authority does not match the exact executor substrate"
        )

    return {
        "task": task_snapshot,
        "task_sha256": _task_sha256(task_snapshot),
        "fixed_command_id": fixed_command_id,
        "catalog": catalog_snapshot,
        "toolchain": toolchain_snapshot,
        "isolation_attestation": attestation_snapshot,
        "physical_verifier": physical_verifier,
        "leased_registry": leased,
        "signed_runtime_closure": signed_closure_snapshot,
        "runtime_closure_verifier": runtime_closure_verifier,
        "trusted_runtime_root": Path(verified_runtime_root),
        "git_runner": git_runner,
        "trusted_git_runtime_receipt": git_receipt,
        "trusted_git_operation_root": raw_operation_root,
        "workspace_root": raw_workspace,
        "workspace_root_path_sha256": workspace_path_sha,
        "workspace_root_authority_sha256": workspace_authority_sha,
        "control_plane_root": raw_control_plane,
        "toolhost_sha256": toolhost_sha,
        "source_env": dict(TIER_A_APPLICATION_ENVIRONMENT),
        "source_environment_sha256": source_environment_sha256(),
    }


__all__: list[str] = []
