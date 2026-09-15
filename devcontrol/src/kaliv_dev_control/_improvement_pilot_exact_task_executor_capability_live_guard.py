"""Fresh non-executing guard for ADR-DC-036 process-local executor capability.

A materialized capability is intentionally process-local, but process locality alone is
not freshness.  This guard revalidates every non-executing trust anchor whenever a
later boundary asks for the live capability inputs.  It never starts Git or the pilot
command; all checks are file/identity/verifier checks only.
"""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .tier_a_authority import tier_a_toolhost_sha256, workspace_root_authority_sha256


class PilotExactTaskExecutorCapabilityLiveGuardError(ValueError):
    """The live ADR-DC-036 capability no longer matches current host authority."""


def install_pilot_exact_task_executor_capability_live_guard(implementation: Any) -> None:
    if implementation is None:
        raise PilotExactTaskExecutorCapabilityLiveGuardError(
            "executor capability implementation is unavailable"
        )
    marker = "_pilot_exact_task_executor_capability_live_guard_installed"
    if getattr(implementation, marker, False):
        return

    original_get = implementation._get_live_capability_inputs

    def guarded_get(value: Any) -> Mapping[str, Any] | None:
        inputs = original_get(value)
        if inputs is None:
            return None
        try:
            task_binding = inputs["task_binding"]
            receipt = inputs["admission_receipt"]
            task = inputs["task"]
            catalog = inputs["catalog"]
            toolchain = inputs["toolchain"]
            attestation = inputs["isolation_attestation"]
            physical_verifier = inputs["physical_verifier"]
            leased = inputs["leased_registry"]
            signed_closure = inputs["signed_runtime_closure"]
            runtime_verifier = inputs["runtime_closure_verifier"]
            trusted_runtime_root = Path(inputs["trusted_runtime_root"])
            git_runner = inputs["git_runner"]
            workspace_root = Path(inputs["workspace_root"])
            control_plane_root = Path(inputs["control_plane_root"])

            specification = catalog.resolve(value.fixed_command_id)
            bindings = toolchain.to_dict()["bindings"]
            if (
                catalog.command_ids != (value.fixed_command_id,)
                or len(bindings) != 1
                or bindings[0]["tool_id"] != specification.tool_id
                or leased.catalog.sha256 != catalog.sha256
                or leased.toolchain.sha256 != toolchain.sha256
            ):
                return None

            # Stable in-process identities must still reproduce the durable evidence.
            if (
                task_binding.sha256 != value.task_binding_sha256
                or receipt.sha256 != value.admission_receipt_sha256
                or receipt.execution_nonce_sha256 != value.execution_nonce_sha256
                or receipt.transaction_authenticated is not True
                or receipt.task_execution_authorized is not True
                or receipt.task_execution_started is not False
                or receipt.execution_consumed is not False
                or implementation._task_sha256(task) != value.development_task_sha256
                or task.task_id != value.development_task_id
                or catalog.sha256 != value.catalog_sha256
                or toolchain.sha256 != value.toolchain_sha256
                or implementation._attestation_sha256(attestation)
                != value.isolation_attestation_sha256
                or leased.lease.sha256 != value.lease_sha256
                or leased.lease.signed_report_sha256 != value.physical_report_sha256
                or signed_closure.sha256 != value.signed_runtime_closure_sha256
                or signed_closure.manifest.sha256
                != value.runtime_closure_manifest_sha256
                or signed_closure.manifest.trusted_runtime_root_sha256
                != value.trusted_runtime_root_sha256
                or implementation._source_environment_sha256()
                != value.source_environment_sha256
                or dict(inputs["source_env"])
                != dict(implementation.TIER_A_APPLICATION_ENVIRONMENT)
                or inputs["process_memory_bytes"] != value.process_memory_bytes
                or inputs["active_process_limit"] != value.active_process_limit
            ):
                return None

            # Fresh physical evidence verification catches expiry, signature, probe,
            # file and host-custody changes without launching a process.
            physical_verifier.verify(attestation)
            leased.lease.verify_attestation(attestation)

            # Fresh runtime-closure verification rereads the signed entrypoint/files.
            verified_root, _ = runtime_verifier.verify(
                signed_closure,
                leased,
                task,
                value.fixed_command_id,
                trusted_runtime_root=trusted_runtime_root,
            )
            if Path(verified_root) != trusted_runtime_root:
                return None

            # Staged Git verification is deliberately process-free.  Do not call
            # TrustedGitRunner.run/evidence here: evidence() starts `git --version`.
            git_runner.runtime.verify()
            git_runner._verify_isolation()
            if (
                git_runner.runtime.receipt.sha256
                != value.trusted_git_runtime_receipt_sha256
                or git_runner.runtime.receipt.manifest.sha256
                != value.trusted_git_runtime_manifest_sha256
                or implementation._path_sha256(Path(git_runner.operation_root))
                != value.trusted_git_operation_root_path_sha256
            ):
                return None

            # The signed workspace-path digest is upstream authority and was already
            # checked at materialization. Freshness re-checks the canonical workspace
            # object identity plus the control-plane/toolhost files themselves.
            if (
                workspace_root_authority_sha256(workspace_root)
                != value.workspace_root_authority_sha256
                or tier_a_toolhost_sha256(control_plane_root) != value.toolhost_sha256
            ):
                return None
        except Exception:
            return None

        # Never expose the registry's mutable backing dictionary. The reviewed
        # source environment is frozen separately because it is the only nested
        # mutable mapping retained by the capability.
        frozen = dict(inputs)
        frozen["source_env"] = MappingProxyType(dict(inputs["source_env"]))
        return MappingProxyType(frozen)

    implementation._get_live_capability_inputs = guarded_get
    setattr(implementation, marker, True)


__all__: list[str] = []
