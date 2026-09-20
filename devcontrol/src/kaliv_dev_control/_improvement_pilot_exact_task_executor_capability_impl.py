"""Non-executing ADR-DC-036 materialization of one exact Tier-A executor capability.

The durable artifact records exactly which already-reviewed Tier-A authority was
materialized.  It is not itself executor authority: only the exact object returned
by one successful materialization retains process-local live inputs.  Canonical
serialization therefore preserves audit evidence while deliberately dropping the
live capability needed by a later one-shot executor boundary.

This module never calls ``run_verified_tier_a_command`` or
``run_single_verified_tier_a_command_with_receipt`` and never invokes
``TrustedGitRunner.run/evidence``.  Physical isolation, runtime closure, staged
Git runtime, workspace identity and toolhost identity are verified without
starting the pilot command.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ._improvement_pilot_start_consumption_impl import _path_sha256
from ._tier_a_environment import TIER_A_APPLICATION_ENVIRONMENT
from ._tier_a_materialization import LeasedCatalogMaterializer, LeasedCommandRegistry
from .catalog import IsolationAttestation, ModelRigCommandCatalog, Toolchain
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_model import SignedRuntimeClosureManifest
from .runtime_closure_verify import RuntimeClosureVerifier
from .tier_a_authority import tier_a_toolhost_sha256, workspace_root_authority_sha256
from .trusted_git_runtime_runner import TrustedGitRunner
from . import _improvement_pilot_exact_task_tier_a_substrate as tier_a_substrate
from .improvement_pilot_exact_task_development_task_binding import (
    PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY,
    PilotExactTaskDevelopmentTaskBinding,
)
from .improvement_pilot_exact_task_execution_admission import (
    PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY,
    PilotExactTaskExecutionAdmissionReceipt,
)

PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-executor-capability/v1"
)
PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY = (
    "live-materialized-one-dc-l16-tier-a-executor-capability-only"
)
PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES = 512 * 1024 * 1024
PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT = 8
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


class PilotExactTaskExecutorCapabilityError(ValueError):
    """One exact non-executing Tier-A capability could not be materialized safely."""


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
        raise PilotExactTaskExecutorCapabilityError(
            "exact-task executor capability is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskExecutorCapabilityError(f"{name} is invalid")
    return value


def _task_sha256(task: DevelopmentTask) -> str:
    if type(task) is not DevelopmentTask:
        raise PilotExactTaskExecutorCapabilityError("exact DevelopmentTask is required")
    return _sha256_text(task.canonical_json())


def _attestation_sha256(attestation: IsolationAttestation) -> str:
    if type(attestation) is not IsolationAttestation:
        raise PilotExactTaskExecutorCapabilityError(
            "exact IsolationAttestation is required"
        )
    return _sha256_text(attestation.canonical_json())


def _source_environment_sha256() -> str:
    return _sha256_text(
        _canonical(dict(sorted(TIER_A_APPLICATION_ENVIRONMENT.items())))
    )


def _require_binding(value: Any) -> PilotExactTaskDevelopmentTaskBinding:
    if type(value) is not PilotExactTaskDevelopmentTaskBinding:
        raise PilotExactTaskExecutorCapabilityError(
            "exact ADR-DC-035 DevelopmentTask binding is required"
        )
    try:
        replayed = PilotExactTaskDevelopmentTaskBinding.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-035 binding replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-035 binding replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
        or value.host_registry_verified is not True
        or value.pilot_task_mapping_verified is not True
        or value.development_task_materialized is not True
        or value.single_fixed_command_verified is not True
        or value.execution_plan_materialized is not False
        or value.execution_consumed is not False
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskExecutorCapabilityError(
            "executor capability requires one inert verified ADR-DC-035 binding"
        )
    return value


def _require_live_receipt(
    binding: PilotExactTaskDevelopmentTaskBinding,
    value: Any,
) -> PilotExactTaskExecutionAdmissionReceipt:
    if type(value) is not PilotExactTaskExecutionAdmissionReceipt:
        raise PilotExactTaskExecutorCapabilityError(
            "exact live ADR-DC-033 admission receipt is required"
        )
    try:
        replayed = PilotExactTaskExecutionAdmissionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-033 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-033 receipt replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        or value.task_execution_authorized is not True
        or value.task_execution_started is not False
        or value.execution_consumed is not False
        or value.transaction_authenticated is not True
    ):
        raise PilotExactTaskExecutorCapabilityError(
            "executor capability requires the live unconsumed ADR-DC-033 receipt"
        )
    requirements = binding.plan_requirements
    if (
        binding.admission_receipt_sha256 != value.sha256
        or binding.execution_nonce_sha256 != value.execution_nonce_sha256
        or requirements.admission_receipt_sha256 != value.sha256
        or requirements.admission_receipt.to_dict() != value.to_dict()
    ):
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-035 binding does not name this exact live ADR-DC-033 receipt"
        )
    return value


def _snapshot_task(binding: PilotExactTaskDevelopmentTaskBinding) -> DevelopmentTask:
    try:
        task = DevelopmentTask.from_mapping(binding.development_task.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-035 DevelopmentTask could not be snapshotted"
        ) from exc
    if (
        task.task_id != binding.development_task_id
        or _task_sha256(task) != binding.development_task_sha256
        or task.repository != binding.repository
        or task.base_sha != binding.base_sha
        or task.allowed_command_ids != (binding.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
    ):
        raise PilotExactTaskExecutorCapabilityError(
            "ADR-DC-035 DevelopmentTask identity changed before materialization"
        )
    return task


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], dict[str, Any]]] = {}

    def mark(value: Any, inputs: dict[str, Any]) -> None:
        key = id(value)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            value.sha256,
            weakref.ref(value, cleanup),
            inputs,
        )

    def get(value: Any) -> dict[str, Any] | None:
        entry = records.get(id(value))
        if entry is None:
            return None
        pid, digest, ref, inputs = entry
        if pid != os.getpid() or ref() is not value:
            return None
        try:
            if value.sha256 != digest:
                return None
            live_receipt = inputs["admission_receipt"]
            git_runner = inputs["git_runner"]
            if live_receipt.transaction_authenticated is not True:
                return None
            git_runner.runtime.verify()
            if git_runner.runtime.receipt.sha256 != value.trusted_git_runtime_receipt_sha256:
                return None
        except Exception:
            return None
        return inputs

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_live_capability, _get_live_capability_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskExecutorCapability:
    task_binding: PilotExactTaskDevelopmentTaskBinding
    task_binding_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    fixed_command_id: str
    catalog_sha256: str
    toolchain_sha256: str
    isolation_attestation_sha256: str
    lease_sha256: str
    physical_report_sha256: str
    signed_runtime_closure_sha256: str
    runtime_closure_manifest_sha256: str
    trusted_runtime_root_sha256: str
    trusted_git_runtime_receipt_sha256: str
    trusted_git_runtime_manifest_sha256: str
    trusted_git_operation_root_path_sha256: str
    workspace_root_path_sha256: str
    workspace_root_authority_sha256: str
    toolhost_sha256: str
    source_environment_sha256: str
    process_memory_bytes: int
    active_process_limit: int
    executor_capability_materialized: bool = True
    physical_isolation_verified: bool = True
    runtime_closure_verified: bool = True
    trusted_git_runtime_verified: bool = True
    workspace_identity_verified: bool = True
    control_plane_toolhost_verified: bool = True
    execution_plan_materialized: bool = True
    execution_consumed: bool = False
    task_execution_started: bool = False
    task_execution_completed: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability schema is unsupported"
            )
        binding = _require_binding(self.task_binding)
        for name in (
            "task_binding_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "catalog_sha256",
            "toolchain_sha256",
            "isolation_attestation_sha256",
            "lease_sha256",
            "physical_report_sha256",
            "signed_runtime_closure_sha256",
            "runtime_closure_manifest_sha256",
            "trusted_runtime_root_sha256",
            "trusted_git_runtime_receipt_sha256",
            "trusted_git_runtime_manifest_sha256",
            "trusted_git_operation_root_path_sha256",
            "workspace_root_path_sha256",
            "workspace_root_authority_sha256",
            "toolhost_sha256",
            "source_environment_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if not isinstance(self.development_task_id, str) or _TASK_ID.fullmatch(
            self.development_task_id
        ) is None:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability DevelopmentTask id is invalid"
            )
        if not isinstance(self.fixed_command_id, str) or _COMMAND_ID.fullmatch(
            self.fixed_command_id
        ) is None:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability command id is invalid"
            )
        if (
            isinstance(self.process_memory_bytes, bool)
            or self.process_memory_bytes != PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES
            or isinstance(self.active_process_limit, bool)
            or self.active_process_limit != PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT
        ):
            raise PilotExactTaskExecutorCapabilityError(
                "executor native process limits are not the reviewed fixed values"
            )
        expected = {
            "task_binding_sha256": binding.sha256,
            "admission_receipt_sha256": binding.admission_receipt_sha256,
            "execution_nonce_sha256": binding.execution_nonce_sha256,
            "development_task_id": binding.development_task_id,
            "development_task_sha256": binding.development_task_sha256,
            "fixed_command_id": binding.fixed_command_id,
            "workspace_root_path_sha256": binding.workspace_root_path_sha256,
            "source_environment_sha256": _source_environment_sha256(),
        }
        mismatch = next(
            (name for name, expected_value in expected.items() if getattr(self, name) != expected_value),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutorCapabilityError(
                f"executor capability identity mismatch: {mismatch}"
            )
        required_true = (
            "executor_capability_materialized",
            "physical_isolation_verified",
            "runtime_closure_verified",
            "trusted_git_runtime_verified",
            "workspace_identity_verified",
            "control_plane_toolhost_verified",
            "execution_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability verification flags must stay true"
            )
        forced_false = (
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability authority is unsupported"
            )

    @property
    def materialization_authenticated(self) -> bool:
        return _get_live_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_binding": self.task_binding.to_dict(),
            "task_binding_sha256": self.task_binding_sha256,
            "admission_receipt_sha256": self.admission_receipt_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "development_task_id": self.development_task_id,
            "development_task_sha256": self.development_task_sha256,
            "fixed_command_id": self.fixed_command_id,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "isolation_attestation_sha256": self.isolation_attestation_sha256,
            "lease_sha256": self.lease_sha256,
            "physical_report_sha256": self.physical_report_sha256,
            "signed_runtime_closure_sha256": self.signed_runtime_closure_sha256,
            "runtime_closure_manifest_sha256": self.runtime_closure_manifest_sha256,
            "trusted_runtime_root_sha256": self.trusted_runtime_root_sha256,
            "trusted_git_runtime_receipt_sha256": self.trusted_git_runtime_receipt_sha256,
            "trusted_git_runtime_manifest_sha256": self.trusted_git_runtime_manifest_sha256,
            "trusted_git_operation_root_path_sha256": self.trusted_git_operation_root_path_sha256,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "workspace_root_authority_sha256": self.workspace_root_authority_sha256,
            "toolhost_sha256": self.toolhost_sha256,
            "source_environment_sha256": self.source_environment_sha256,
            "process_memory_bytes": self.process_memory_bytes,
            "active_process_limit": self.active_process_limit,
            "executor_capability_materialized": self.executor_capability_materialized,
            "physical_isolation_verified": self.physical_isolation_verified,
            "runtime_closure_verified": self.runtime_closure_verified,
            "trusted_git_runtime_verified": self.trusted_git_runtime_verified,
            "workspace_identity_verified": self.workspace_identity_verified,
            "control_plane_toolhost_verified": self.control_plane_toolhost_verified,
            "execution_plan_materialized": self.execution_plan_materialized,
            "execution_consumed": self.execution_consumed,
            "task_execution_started": self.task_execution_started,
            "task_execution_completed": self.task_execution_completed,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutorCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability fields mismatch"
            )
        data = dict(value)
        data["task_binding"] = PilotExactTaskDevelopmentTaskBinding.from_mapping(
            data["task_binding"]
        )
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskExecutorCapability":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskExecutorCapabilityError(
                "executor capability JSON is invalid"
            ) from exc
        return cls.from_mapping(value)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_executor_capability(
    *,
    task_binding: PilotExactTaskDevelopmentTaskBinding,
    admission_receipt: PilotExactTaskExecutionAdmissionReceipt,
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
) -> PilotExactTaskExecutorCapability:
    """Materialize one live Tier-A capability without starting any command."""
    binding = _require_binding(task_binding)
    live_receipt = _require_live_receipt(binding, admission_receipt)
    task = _snapshot_task(binding)
    try:
        substrate = tier_a_substrate.materialize_verified_tier_a_substrate(
            task=task,
            fixed_command_id=binding.fixed_command_id,
            workspace_root_path_sha256=binding.workspace_root_path_sha256,
            catalog=catalog,
            toolchain=toolchain,
            isolation_attestation=isolation_attestation,
            physical_verifier=physical_verifier,
            signed_runtime_closure=signed_runtime_closure,
            runtime_closure_verifier=runtime_closure_verifier,
            trusted_runtime_root=trusted_runtime_root,
            git_runner=git_runner,
            workspace_root=workspace_root,
            control_plane_root=control_plane_root,
            path_sha256=_path_sha256,
        )
    except tier_a_substrate.PilotExactTaskTierASubstrateError as exc:
        raise PilotExactTaskExecutorCapabilityError(str(exc)) from exc

    task_snapshot = substrate["task"]
    catalog_snapshot = substrate["catalog"]
    toolchain_snapshot = substrate["toolchain"]
    attestation_snapshot = substrate["isolation_attestation"]
    leased = substrate["leased_registry"]
    signed_closure_snapshot = substrate["signed_runtime_closure"]
    manifest = signed_closure_snapshot.manifest
    git_receipt = substrate["trusted_git_runtime_receipt"]

    capability = PilotExactTaskExecutorCapability(
        task_binding=binding,
        task_binding_sha256=binding.sha256,
        admission_receipt_sha256=live_receipt.sha256,
        execution_nonce_sha256=live_receipt.execution_nonce_sha256,
        development_task_id=task_snapshot.task_id,
        development_task_sha256=substrate["task_sha256"],
        fixed_command_id=binding.fixed_command_id,
        catalog_sha256=catalog_snapshot.sha256,
        toolchain_sha256=toolchain_snapshot.sha256,
        isolation_attestation_sha256=_attestation_sha256(attestation_snapshot),
        lease_sha256=leased.lease.sha256,
        physical_report_sha256=leased.lease.signed_report_sha256,
        signed_runtime_closure_sha256=signed_closure_snapshot.sha256,
        runtime_closure_manifest_sha256=manifest.sha256,
        trusted_runtime_root_sha256=manifest.trusted_runtime_root_sha256,
        trusted_git_runtime_receipt_sha256=git_receipt.sha256,
        trusted_git_runtime_manifest_sha256=git_receipt.manifest.sha256,
        trusted_git_operation_root_path_sha256=_path_sha256(
            substrate["trusted_git_operation_root"]
        ),
        workspace_root_path_sha256=substrate["workspace_root_path_sha256"],
        workspace_root_authority_sha256=substrate["workspace_root_authority_sha256"],
        toolhost_sha256=substrate["toolhost_sha256"],
        source_environment_sha256=substrate["source_environment_sha256"],
        process_memory_bytes=PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES,
        active_process_limit=PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT,
    )
    _mark_live_capability(
        capability,
        {
            "task_binding": binding,
            "admission_receipt": live_receipt,
            "task": task_snapshot,
            "catalog": catalog_snapshot,
            "toolchain": toolchain_snapshot,
            "isolation_attestation": attestation_snapshot,
            "physical_verifier": substrate["physical_verifier"],
            "leased_registry": leased,
            "signed_runtime_closure": signed_closure_snapshot,
            "runtime_closure_verifier": substrate["runtime_closure_verifier"],
            "trusted_runtime_root": substrate["trusted_runtime_root"],
            "git_runner": substrate["git_runner"],
            "workspace_root": substrate["workspace_root"],
            "control_plane_root": substrate["control_plane_root"],
            "source_env": dict(substrate["source_env"]),
            "process_memory_bytes": PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES,
            "active_process_limit": PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT,
        },
    )
    if capability.materialization_authenticated is not True:
        raise PilotExactTaskExecutorCapabilityError(
            "live executor capability provenance could not be retained"
        )
    return capability


# Production facade installs the public host-pinned resolver later.
def materialize_pilot_exact_task_executor_capability(**_: Any) -> PilotExactTaskExecutorCapability:
    raise PilotExactTaskExecutorCapabilityError(
        "production executor capability boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES",
    "PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT",
    "PilotExactTaskExecutorCapabilityError",
    "PilotExactTaskExecutorCapability",
]
