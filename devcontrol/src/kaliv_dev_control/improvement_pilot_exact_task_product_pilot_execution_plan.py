"""ADR-DC-107 product-pilot execution plan bound to one frozen workspace snapshot.

Consumes one live ADR-DC-106 workspace-snapshot receipt and materializes an
in-memory execution plan for the existing reviewed read-only
`modelrig.version.check` command.

The boundary never captures or substitutes a workspace snapshot. Live authority
is retained only while ADR-DC-106 still proves that the current workspace equals
the exact frozen snapshot already named by the receipt. No command is launched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from typing import Any, Mapping

from .contract import DevelopmentTask
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID
from .tier_a_command_receipt import GitWorkspaceSnapshot
from . import improvement_pilot_exact_task_product_pilot_workspace_snapshot as snapshot_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-plan/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY = (
    "live-product-pilot-frozen-snapshot-execution-plan-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE = (
    "started-product-pilot-reviewed-version-check-frozen-snapshot-plan-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotExecutionPlanError(ValueError):
    """The frozen product-pilot workspace state cannot safely form a plan."""


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
        raise PilotExactTaskProductPilotExecutionPlanError(
            "product-pilot execution plan is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutionPlanError(f"{name} is invalid")
    return value


def _task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _command_spec_sha256(live: Mapping[str, Any], command_id: str) -> str:
    try:
        specification = live["catalog"].resolve(command_id)
        payload = specification.to_dict()
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "reviewed product-pilot command specification is unavailable"
        ) from exc
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _require_live_snapshot(value: Any):
    if (
        type(value)
        is not snapshot_boundary.PilotExactTaskProductPilotWorkspaceSnapshotReceipt
        or value.snapshot_authenticated is not True
        or value.product_pilot_started is not True
        or value.executor_capability_authenticated is not True
        or value.fresh_substrate_revalidated is not True
        or value.workspace_snapshot_materialized is not True
        or value.workspace_head_matches_task_base is not True
        or value.workspace_has_unstaged_or_untracked is not False
        or value.execution_plan_materialization_authorized is not True
        or value.execution_plan_materialized is not False
        or value.task_execution_authorized is not False
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.next_boundary_execution_plan_required is not True
        or value.nonce_reusable is not False
        or value.fixed_command_id != VERSION_CHECK_COMMAND_ID
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(
            "live inert ADR-DC-106 workspace snapshot is required"
        )
    live = snapshot_boundary._get_live_product_pilot_workspace_snapshot_inputs(
        value
    )
    if live is None:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "ADR-DC-106 frozen workspace snapshot is no longer live"
        )
    task = live.get("task")
    fresh = live.get("workspace_snapshot")
    if (
        type(task) is not DevelopmentTask
        or type(fresh) is not GitWorkspaceSnapshot
        or task.task_id != value.development_task_id
        or _task_sha256(task) != value.development_task_sha256
        or task.base_sha != value.development_task_base_sha
        or task.allowed_command_ids != (value.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
        or fresh.sha256 != value.workspace_snapshot_sha256
        or value.workspace_snapshot.sha256 != value.workspace_snapshot_sha256
        or fresh.sha256 != value.workspace_snapshot.sha256
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(
            "ADR-DC-106 task or frozen workspace provenance is inconsistent"
        )
    capability = live.get("executor_capability")
    if capability is None or capability.sha256 != value.executor_capability_sha256:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "ADR-DC-106 executor-capability provenance is inconsistent"
        )
    return value, live, task, capability


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutionPlanReceipt:
    workspace_snapshot_receipt_sha256: str
    executor_capability_sha256: str
    execution_admission_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    command_spec_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    workspace_root_path_sha256: str
    workspace_root_authority_sha256: str
    catalog_sha256: str
    toolchain_sha256: str
    lease_sha256: str
    physical_report_sha256: str
    signed_runtime_closure_sha256: str
    runtime_closure_manifest_sha256: str
    trusted_git_runtime_receipt_sha256: str
    trusted_git_runtime_manifest_sha256: str
    toolhost_sha256: str
    source_environment_sha256: str
    workspace_snapshot_sha256: str
    workspace_snapshot: GitWorkspaceSnapshot
    task_max_runtime_seconds: int
    task_max_output_bytes: int
    process_memory_bytes: int
    active_process_limit: int
    product_pilot_started: bool = True
    workspace_snapshot_authenticated: bool = True
    exact_workspace_snapshot_bound: bool = True
    command_specification_bound: bool = True
    execution_plan_materialized: bool = True
    task_execution_authorized: bool = True
    one_shot_task_execution_required: bool = True
    pre_launch_substrate_revalidation_required: bool = True
    pre_launch_workspace_snapshot_revalidation_required: bool = True
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
    next_boundary_task_execution_required: bool = True
    plan_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan identity is unsupported"
            )
        for name in (
            "workspace_snapshot_receipt_sha256",
            "executor_capability_sha256",
            "execution_admission_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "command_spec_sha256",
            "workspace_root_path_sha256",
            "workspace_root_authority_sha256",
            "catalog_sha256",
            "toolchain_sha256",
            "lease_sha256",
            "physical_report_sha256",
            "signed_runtime_closure_sha256",
            "runtime_closure_manifest_sha256",
            "trusted_git_runtime_receipt_sha256",
            "trusted_git_runtime_manifest_sha256",
            "toolhost_sha256",
            "source_environment_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        if self.fixed_command_id != VERSION_CHECK_COMMAND_ID:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan command is not the reviewed command"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan repository identity is invalid"
            )
        if type(self.workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution plan lacks canonical workspace evidence"
            )
        if self.workspace_snapshot.sha256 != self.workspace_snapshot_sha256:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan snapshot hash is inconsistent"
            )
        if (
            self.workspace_snapshot.head_sha != self.development_task_base_sha
            or self.workspace_snapshot.has_unstaged_or_untracked
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan snapshot is unsafe"
            )
        if (
            isinstance(self.task_max_runtime_seconds, bool)
            or not isinstance(self.task_max_runtime_seconds, int)
            or not 1 <= self.task_max_runtime_seconds <= 86_400
            or isinstance(self.task_max_output_bytes, bool)
            or not isinstance(self.task_max_output_bytes, int)
            or not 1_024 <= self.task_max_output_bytes <= 32 * 1024 * 1024
            or isinstance(self.process_memory_bytes, bool)
            or self.process_memory_bytes != 512 * 1024 * 1024
            or isinstance(self.active_process_limit, bool)
            or self.active_process_limit != 8
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan budgets are invalid"
            )
        required_true = (
            "product_pilot_started",
            "workspace_snapshot_authenticated",
            "exact_workspace_snapshot_bound",
            "command_specification_bound",
            "execution_plan_materialized",
            "task_execution_authorized",
            "one_shot_task_execution_required",
            "pre_launch_substrate_revalidation_required",
            "pre_launch_workspace_snapshot_revalidation_required",
            "next_boundary_task_execution_required",
        )
        forced_false = (
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
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution plan lacks mandatory authority"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution plan grants premature mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_product_pilot_execution_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "workspace_snapshot"
        }
        result["workspace_snapshot"] = self.workspace_snapshot.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan fields mismatch"
            )
        raw = dict(value)
        try:
            raw["workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
                raw["workspace_snapshot"]
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan workspace evidence is invalid"
            ) from exc
        return cls(**raw)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutionPlanReceipt,
        *,
        workspace_snapshot_receipt: snapshot_boundary.PilotExactTaskProductPilotWorkspaceSnapshotReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            workspace_snapshot_receipt,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, workspace_snapshot_receipt = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or workspace_snapshot_receipt.sha256
            != receipt.workspace_snapshot_receipt_sha256
        ):
            return None
        try:
            source, live, task, capability = _require_live_snapshot(
                workspace_snapshot_receipt
            )
            command_spec_sha = _command_spec_sha256(live, receipt.fixed_command_id)
        except Exception:
            return None
        checks = (
            (source.workspace_snapshot_sha256, receipt.workspace_snapshot_sha256),
            (source.workspace_snapshot.sha256, receipt.workspace_snapshot.sha256),
            (source.executor_capability_sha256, receipt.executor_capability_sha256),
            (source.execution_admission_sha256, receipt.execution_admission_sha256),
            (source.execution_nonce_sha256, receipt.execution_nonce_sha256),
            (source.development_task_sha256, receipt.development_task_sha256),
            (source.development_task_base_sha, receipt.development_task_base_sha),
            (source.workspace_root_path_sha256, receipt.workspace_root_path_sha256),
            (
                source.workspace_root_authority_sha256,
                receipt.workspace_root_authority_sha256,
            ),
            (source.catalog_sha256, receipt.catalog_sha256),
            (source.toolchain_sha256, receipt.toolchain_sha256),
            (source.lease_sha256, receipt.lease_sha256),
            (
                source.signed_runtime_closure_sha256,
                receipt.signed_runtime_closure_sha256,
            ),
            (
                source.trusted_git_runtime_receipt_sha256,
                receipt.trusted_git_runtime_receipt_sha256,
            ),
            (
                source.trusted_git_runtime_manifest_sha256,
                receipt.trusted_git_runtime_manifest_sha256,
            ),
            (source.toolhost_sha256, receipt.toolhost_sha256),
            (source.source_environment_sha256, receipt.source_environment_sha256),
            (command_spec_sha, receipt.command_spec_sha256),
            (_task_sha256(task), receipt.development_task_sha256),
            (task.budget.max_runtime_seconds, receipt.task_max_runtime_seconds),
            (task.budget.max_output_bytes, receipt.task_max_output_bytes),
            (capability.repository, receipt.repository),
            (capability.repository_id, receipt.repository_id),
            (capability.merge_commit_sha, receipt.merge_commit_sha),
            (capability.physical_report_sha256, receipt.physical_report_sha256),
            (
                capability.runtime_closure_manifest_sha256,
                receipt.runtime_closure_manifest_sha256,
            ),
            (capability.process_memory_bytes, receipt.process_memory_bytes),
            (capability.active_process_limit, receipt.active_process_limit),
        )
        if any(left != right for left, right in checks):
            return None
        frozen = dict(live)
        frozen["workspace_snapshot_receipt"] = source
        frozen["workspace_snapshot"] = source.workspace_snapshot
        frozen["executor_capability"] = capability
        return frozen

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_execution_plan_authenticated,
    _get_live_product_pilot_execution_plan_inputs,
) = _live_registry()


def materialize_pilot_exact_task_product_pilot_execution_plan(
    workspace_snapshot_receipt: snapshot_boundary.PilotExactTaskProductPilotWorkspaceSnapshotReceipt,
) -> PilotExactTaskProductPilotExecutionPlanReceipt:
    """Bind an execution plan to the exact ADR-DC-106 snapshot without replacing it."""
    source, live, task, capability = _require_live_snapshot(
        workspace_snapshot_receipt
    )
    command_spec_sha = _command_spec_sha256(live, source.fixed_command_id)
    receipt = PilotExactTaskProductPilotExecutionPlanReceipt(
        workspace_snapshot_receipt_sha256=source.sha256,
        executor_capability_sha256=source.executor_capability_sha256,
        execution_admission_sha256=source.execution_admission_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_id=source.development_task_id,
        development_task_sha256=source.development_task_sha256,
        development_task_base_sha=source.development_task_base_sha,
        fixed_command_id=source.fixed_command_id,
        command_spec_sha256=command_spec_sha,
        repository=capability.repository,
        repository_id=capability.repository_id,
        merge_commit_sha=capability.merge_commit_sha,
        workspace_root_path_sha256=source.workspace_root_path_sha256,
        workspace_root_authority_sha256=source.workspace_root_authority_sha256,
        catalog_sha256=source.catalog_sha256,
        toolchain_sha256=source.toolchain_sha256,
        lease_sha256=source.lease_sha256,
        physical_report_sha256=capability.physical_report_sha256,
        signed_runtime_closure_sha256=source.signed_runtime_closure_sha256,
        runtime_closure_manifest_sha256=capability.runtime_closure_manifest_sha256,
        trusted_git_runtime_receipt_sha256=source.trusted_git_runtime_receipt_sha256,
        trusted_git_runtime_manifest_sha256=source.trusted_git_runtime_manifest_sha256,
        toolhost_sha256=source.toolhost_sha256,
        source_environment_sha256=source.source_environment_sha256,
        workspace_snapshot_sha256=source.workspace_snapshot_sha256,
        workspace_snapshot=source.workspace_snapshot,
        task_max_runtime_seconds=task.budget.max_runtime_seconds,
        task_max_output_bytes=task.budget.max_output_bytes,
        process_memory_bytes=capability.process_memory_bytes,
        active_process_limit=capability.active_process_limit,
    )
    _mark_product_pilot_execution_plan_authenticated(
        receipt,
        workspace_snapshot_receipt=source,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "product-pilot execution plan lost its exact frozen snapshot authority"
        )
    return receipt


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE",
    "PilotExactTaskProductPilotExecutionPlanError",
    "PilotExactTaskProductPilotExecutionPlanReceipt",
    "materialize_pilot_exact_task_product_pilot_execution_plan",
]
