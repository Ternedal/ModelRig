"""ADR-DC-105 product-pilot executor capability on the existing Tier-A substrate.

Consumes one live ADR-DC-104 execution admission and materializes the exact same
reviewed Tier-A physical/runtime/Git substrate used by legacy ADR-DC-036.

This boundary still never creates an execution plan or starts a command. It
authorizes only the next exact workspace-snapshot execution-plan boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import _improvement_pilot_exact_task_tier_a_substrate as tier_a_substrate
from . import _improvement_pilot_exact_task_executor_capability_production_boundary as executor_production
from . import improvement_pilot_exact_task_product_pilot_execution_admission as admission_boundary
from .catalog import IsolationAttestation, ModelRigCommandCatalog, Toolchain
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_model import SignedRuntimeClosureManifest
from .runtime_closure_verify import RuntimeClosureVerifier
from .trusted_git_runtime_runner import TrustedGitRunner

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-executor-capability/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_AUTHORITY = (
    "live-product-pilot-existing-tier-a-executor-capability-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCOPE = (
    "started-product-pilot-reviewed-version-check-capability-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_PROCESS_MEMORY_BYTES = 512 * 1024 * 1024
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_ACTIVE_PROCESS_LIMIT = 8

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotExecutorCapabilityError(ValueError):
    """The started product pilot cannot safely materialize the reviewed executor."""


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
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "product-pilot executor capability is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotExecutorCapabilityError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutorCapabilityError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutorCapabilityError(f"{name} is invalid")
    return value


def _require_live_admission(value: Any):
    if (
        type(value)
        is not admission_boundary.PilotExactTaskProductPilotExecutionAdmissionReceipt
        or value.admission_authenticated is not True
        or value.start_state_authenticated is not True
        or value.executor_capability_materialization_authorized is not True
        or value.execution_plan_materialization_authorized is not False
        or value.task_execution_authorized is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.next_boundary_executor_capability_required is not True
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "live inert ADR-DC-104 execution admission is required"
        )
    live = admission_boundary._get_live_execution_admission_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "ADR-DC-104 live execution-admission provenance is unavailable"
        )
    task = live.get("development_task")
    if (
        type(task) is not DevelopmentTask
        or task.task_id != value.development_task_id
        or tier_a_substrate._task_sha256(task) != value.development_task_sha256
        or task.base_sha != value.development_task_base_sha
        or task.allowed_command_ids != (value.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
    ):
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "ADR-DC-104 DevelopmentTask provenance is inconsistent"
        )
    return value, live, task


def _execution_nonce_sha256(
    admission: admission_boundary.PilotExactTaskProductPilotExecutionAdmissionReceipt,
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-product-pilot-execution-nonce/v1",
                "execution_admission_sha256": admission.sha256,
                "start_transaction_receipt_sha256": (
                    admission.start_transaction_receipt_sha256
                ),
                "development_task_sha256": admission.development_task_sha256,
                "fixed_command_id": admission.fixed_command_id,
                "workspace_root_path_sha256": admission.workspace_root_path_sha256,
            }
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutorCapabilityReceipt:
    execution_admission_sha256: str
    start_state_source_sha256: str
    start_transaction_receipt_sha256: str
    product_pilot_start_readiness_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    workspace_root_path_sha256: str
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
    workspace_root_authority_sha256: str
    toolhost_sha256: str
    source_environment_sha256: str
    process_memory_bytes: int
    active_process_limit: int
    product_pilot_started: bool = True
    execution_admission_authenticated: bool = True
    executor_capability_materialized: bool = True
    physical_isolation_verified: bool = True
    runtime_closure_verified: bool = True
    trusted_git_runtime_verified: bool = True
    workspace_identity_verified: bool = True
    control_plane_toolhost_verified: bool = True
    fresh_substrate_revalidation_required: bool = True
    fresh_workspace_snapshot_required: bool = True
    execution_plan_materialization_authorized: bool = True
    execution_plan_materialized: bool = False
    task_execution_authorized: bool = False
    task_execution_started: bool = False
    task_execution_completed: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_execution_plan_required: bool = True
    capability_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_AUTHORITY
            or self.capability_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor capability identity is unsupported"
            )
        for name in (
            "execution_admission_sha256",
            "start_state_source_sha256",
            "start_transaction_receipt_sha256",
            "product_pilot_start_readiness_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
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
            "workspace_root_authority_sha256",
            "toolhost_sha256",
            "source_environment_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor capability repository identity is invalid"
            )
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        if (
            isinstance(self.process_memory_bytes, bool)
            or self.process_memory_bytes
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_PROCESS_MEMORY_BYTES
            or isinstance(self.active_process_limit, bool)
            or self.active_process_limit
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_ACTIVE_PROCESS_LIMIT
        ):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor process limits are not reviewed fixed values"
            )

        required_true = (
            "product_pilot_started",
            "execution_admission_authenticated",
            "executor_capability_materialized",
            "physical_isolation_verified",
            "runtime_closure_verified",
            "trusted_git_runtime_verified",
            "workspace_identity_verified",
            "control_plane_toolhost_verified",
            "fresh_substrate_revalidation_required",
            "fresh_workspace_snapshot_required",
            "execution_plan_materialization_authorized",
            "next_boundary_execution_plan_required",
        )
        forced_false = (
            "execution_plan_materialized",
            "task_execution_authorized",
            "task_execution_started",
            "task_execution_completed",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor capability lacks mandatory evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor capability grants premature execution authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_product_pilot_executor_capability_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutorCapabilityError(
                "product-pilot executor capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutorCapabilityReceipt,
        *,
        admission: admission_boundary.PilotExactTaskProductPilotExecutionAdmissionReceipt,
        substrate: Mapping[str, Any],
        path_sha256: Callable[[Path], str],
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            admission,
            dict(substrate),
            path_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, admission, substrate, path_sha256 = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or admission.admission_authenticated is not True
            or admission.sha256 != receipt.execution_admission_sha256
        ):
            return None
        live = admission_boundary._get_live_execution_admission_inputs(admission)
        task = live.get("development_task") if live else None
        if type(task) is not DevelopmentTask:
            return None
        try:
            fresh = tier_a_substrate.materialize_verified_tier_a_substrate(
                task=task,
                fixed_command_id=receipt.fixed_command_id,
                workspace_root_path_sha256=receipt.workspace_root_path_sha256,
                catalog=substrate["catalog"],
                toolchain=substrate["toolchain"],
                isolation_attestation=substrate["isolation_attestation"],
                physical_verifier=substrate["physical_verifier"],
                signed_runtime_closure=substrate["signed_runtime_closure"],
                runtime_closure_verifier=substrate["runtime_closure_verifier"],
                trusted_runtime_root=substrate["trusted_runtime_root"],
                git_runner=substrate["git_runner"],
                workspace_root=substrate["workspace_root"],
                control_plane_root=substrate["control_plane_root"],
                path_sha256=path_sha256,
            )
        except Exception:
            return None
        checks = (
            (fresh["task_sha256"], receipt.development_task_sha256),
            (fresh["catalog"].sha256, receipt.catalog_sha256),
            (fresh["toolchain"].sha256, receipt.toolchain_sha256),
            (
                tier_a_substrate._attestation_sha256(
                    fresh["isolation_attestation"]
                ),
                receipt.isolation_attestation_sha256,
            ),
            (fresh["leased_registry"].lease.sha256, receipt.lease_sha256),
            (
                fresh["leased_registry"].lease.signed_report_sha256,
                receipt.physical_report_sha256,
            ),
            (
                fresh["signed_runtime_closure"].sha256,
                receipt.signed_runtime_closure_sha256,
            ),
            (
                fresh["signed_runtime_closure"].manifest.sha256,
                receipt.runtime_closure_manifest_sha256,
            ),
            (
                fresh["signed_runtime_closure"].manifest.trusted_runtime_root_sha256,
                receipt.trusted_runtime_root_sha256,
            ),
            (
                fresh["trusted_git_runtime_receipt"].sha256,
                receipt.trusted_git_runtime_receipt_sha256,
            ),
            (
                fresh["trusted_git_runtime_receipt"].manifest.sha256,
                receipt.trusted_git_runtime_manifest_sha256,
            ),
            (
                path_sha256(fresh["trusted_git_operation_root"]),
                receipt.trusted_git_operation_root_path_sha256,
            ),
            (
                fresh["workspace_root_authority_sha256"],
                receipt.workspace_root_authority_sha256,
            ),
            (fresh["toolhost_sha256"], receipt.toolhost_sha256),
            (
                fresh["source_environment_sha256"],
                receipt.source_environment_sha256,
            ),
        )
        if any(left != right for left, right in checks):
            return None
        frozen = dict(fresh)
        # The Tier-A substrate intentionally snapshots DevelopmentTask while
        # validating it. Downstream product-pilot boundaries, however, must
        # retain the exact live task object authenticated by the admission
        # registry so repeated provenance checks cannot manufacture a new
        # object identity across the durable nonce boundary.
        frozen["task"] = task
        frozen["execution_admission"] = admission
        return frozen

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_executor_capability_authenticated,
    _get_live_product_pilot_executor_capability_inputs,
) = _live_registry()


def _materialize_verified_product_pilot_executor_capability(
    *,
    execution_admission: admission_boundary.PilotExactTaskProductPilotExecutionAdmissionReceipt,
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
    path_sha256: Callable[[Path], str] = _path_sha256,
) -> PilotExactTaskProductPilotExecutorCapabilityReceipt:
    admission, live, task = _require_live_admission(execution_admission)
    try:
        substrate = tier_a_substrate.materialize_verified_tier_a_substrate(
            task=task,
            fixed_command_id=admission.fixed_command_id,
            workspace_root_path_sha256=admission.workspace_root_path_sha256,
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
            path_sha256=path_sha256,
        )
    except tier_a_substrate.PilotExactTaskTierASubstrateError as exc:
        raise PilotExactTaskProductPilotExecutorCapabilityError(str(exc)) from exc

    leased = substrate["leased_registry"]
    closure = substrate["signed_runtime_closure"]
    git_receipt = substrate["trusted_git_runtime_receipt"]
    receipt = PilotExactTaskProductPilotExecutorCapabilityReceipt(
        execution_admission_sha256=admission.sha256,
        start_state_source_sha256=admission.start_state_source_sha256,
        start_transaction_receipt_sha256=admission.start_transaction_receipt_sha256,
        product_pilot_start_readiness_sha256=(
            admission.product_pilot_start_readiness_sha256
        ),
        execution_nonce_sha256=_execution_nonce_sha256(admission),
        development_task_id=admission.development_task_id,
        development_task_sha256=admission.development_task_sha256,
        development_task_base_sha=admission.development_task_base_sha,
        fixed_command_id=admission.fixed_command_id,
        repository=admission.repository,
        repository_id=admission.repository_id,
        merge_commit_sha=admission.merge_commit_sha,
        workspace_root_path_sha256=admission.workspace_root_path_sha256,
        catalog_sha256=substrate["catalog"].sha256,
        toolchain_sha256=substrate["toolchain"].sha256,
        isolation_attestation_sha256=tier_a_substrate._attestation_sha256(
            substrate["isolation_attestation"]
        ),
        lease_sha256=leased.lease.sha256,
        physical_report_sha256=leased.lease.signed_report_sha256,
        signed_runtime_closure_sha256=closure.sha256,
        runtime_closure_manifest_sha256=closure.manifest.sha256,
        trusted_runtime_root_sha256=closure.manifest.trusted_runtime_root_sha256,
        trusted_git_runtime_receipt_sha256=git_receipt.sha256,
        trusted_git_runtime_manifest_sha256=git_receipt.manifest.sha256,
        trusted_git_operation_root_path_sha256=path_sha256(
            substrate["trusted_git_operation_root"]
        ),
        workspace_root_authority_sha256=substrate["workspace_root_authority_sha256"],
        toolhost_sha256=substrate["toolhost_sha256"],
        source_environment_sha256=substrate["source_environment_sha256"],
        process_memory_bytes=PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_PROCESS_MEMORY_BYTES,
        active_process_limit=PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_ACTIVE_PROCESS_LIMIT,
    )
    _mark_product_pilot_executor_capability_authenticated(
        receipt,
        admission=admission,
        substrate=substrate,
        path_sha256=path_sha256,
    )
    if receipt.capability_authenticated is not True:
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "product-pilot executor capability lost live substrate provenance"
        )
    return receipt


def materialize_pilot_exact_task_product_pilot_executor_capability(
    execution_admission: admission_boundary.PilotExactTaskProductPilotExecutionAdmissionReceipt,
) -> PilotExactTaskProductPilotExecutorCapabilityReceipt:
    """Resolve the canonical Windows Tier-A profile and materialize no command."""
    admission, _live, _task = _require_live_admission(execution_admission)
    try:
        inputs = executor_production._resolve_host_executor_materialization_inputs(
            development_task_sha256=admission.development_task_sha256,
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutorCapabilityError(
            "host-controlled product-pilot executor substrate is unavailable"
        ) from exc
    return _materialize_verified_product_pilot_executor_capability(
        execution_admission=admission,
        **inputs,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_CAPABILITY_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_PROCESS_MEMORY_BYTES",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_ACTIVE_PROCESS_LIMIT",
    "PilotExactTaskProductPilotExecutorCapabilityError",
    "PilotExactTaskProductPilotExecutorCapabilityReceipt",
    "materialize_pilot_exact_task_product_pilot_executor_capability",
]
