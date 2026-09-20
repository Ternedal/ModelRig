"""ADR-DC-106 exact product-pilot execution plan.

Consumes one live ADR-DC-105 executor capability, revalidates its reviewed Tier-A
substrate, captures one exact Trusted-Git workspace snapshot, and materializes a
process-local one-shot execution plan for the existing read-only
`modelrig.version.check` command.

This boundary performs Git reads only. It never stages a runtime closure, starts
the product command, mutates the workspace, or grants any publication authority.
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
from . import improvement_pilot_exact_task_product_pilot_executor_capability as capability_boundary
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-plan/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY = (
    "live-product-pilot-clean-workspace-execution-plan-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE = (
    "started-product-pilot-reviewed-version-check-clean-workspace-plan-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotExecutionPlanError(ValueError):
    """The live product-pilot capability cannot safely form an execution plan."""


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
        spec = live["catalog"].resolve(command_id)
        payload = spec.to_dict()
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "reviewed command specification is unavailable"
        ) from exc
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _require_live_capability(value: Any):
    if (
        type(value)
        is not capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt
        or value.capability_authenticated is not True
        or value.product_pilot_started is not True
        or value.executor_capability_materialized is not True
        or value.execution_plan_materialization_authorized is not True
        or value.execution_plan_materialized is not False
        or value.task_execution_authorized is not False
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.fresh_substrate_revalidation_required is not True
        or value.fresh_workspace_snapshot_required is not True
        or value.next_boundary_execution_plan_required is not True
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(
            "live inert ADR-DC-105 executor capability is required"
        )
    live = capability_boundary._get_live_product_pilot_executor_capability_inputs(
        value
    )
    if live is None:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "ADR-DC-105 live executor substrate is unavailable"
        )
    task = live.get("task")
    if (
        type(task) is not DevelopmentTask
        or task.task_id != value.development_task_id
        or _task_sha256(task) != value.development_task_sha256
        or task.base_sha != value.development_task_base_sha
        or task.allowed_command_ids != (value.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(
            "ADR-DC-105 DevelopmentTask provenance is inconsistent"
        )
    return value, live, task


def _capture_workspace_snapshot(
    *,
    live: Mapping[str, Any],
    task: DevelopmentTask,
) -> tuple[GitWorkspaceSnapshot, str]:
    """Capture one exact clean snapshot while proving Trusted-Git identity stable."""
    try:
        git_runner = live["git_runner"]
        runtime_before = git_runner.evidence()
        evidence = _GitWorkspaceEvidence(live["workspace_root"], task, git_runner)
        snapshot = evidence.snapshot()
        runtime_after = git_runner.evidence()
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "fresh Trusted-Git workspace snapshot failed"
        ) from exc
    if runtime_after.sha256 != runtime_before.sha256:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "Trusted-Git runtime changed during workspace snapshot"
        )
    if snapshot.head_sha != task.base_sha:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "workspace HEAD does not match the exact DevelopmentTask base"
        )
    if (
        snapshot.staged_patch_bytes != 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskProductPilotExecutionPlanError(
            "product-pilot execution requires an exact clean workspace"
        )
    return snapshot, runtime_before.sha256


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutionPlanReceipt:
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
    catalog_sha256: str
    toolchain_sha256: str
    lease_sha256: str
    physical_report_sha256: str
    signed_runtime_closure_sha256: str
    runtime_closure_manifest_sha256: str
    trusted_git_runtime_receipt_sha256: str
    trusted_git_runtime_manifest_sha256: str
    git_runtime_evidence_sha256: str
    workspace_snapshot: GitWorkspaceSnapshot
    workspace_snapshot_sha256: str
    task_max_runtime_seconds: int
    task_max_output_bytes: int
    process_memory_bytes: int
    active_process_limit: int
    product_pilot_started: bool = True
    executor_capability_authenticated: bool = True
    fresh_substrate_revalidated: bool = True
    workspace_snapshot_frozen: bool = True
    workspace_clean: bool = True
    git_runtime_stable: bool = True
    execution_plan_materialized: bool = True
    task_execution_authorized: bool = True
    one_shot_execution_required: bool = True
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
            "executor_capability_sha256",
            "execution_admission_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "command_spec_sha256",
            "workspace_root_path_sha256",
            "catalog_sha256",
            "toolchain_sha256",
            "lease_sha256",
            "physical_report_sha256",
            "signed_runtime_closure_sha256",
            "runtime_closure_manifest_sha256",
            "trusted_git_runtime_receipt_sha256",
            "trusted_git_runtime_manifest_sha256",
            "git_runtime_evidence_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
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
                "product-pilot execution plan requires an exact GitWorkspaceSnapshot"
            )
        if self.workspace_snapshot.sha256 != self.workspace_snapshot_sha256:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "workspace snapshot hash does not match the frozen snapshot"
            )
        if (
            self.workspace_snapshot.head_sha != self.development_task_base_sha
            or self.workspace_snapshot.staged_patch_bytes != 0
            or self.workspace_snapshot.unstaged_patch_bytes != 0
            or self.workspace_snapshot.untracked_path_count != 0
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "workspace snapshot is not exact-base clean"
            )
        if (
            isinstance(self.task_max_runtime_seconds, bool)
            or not isinstance(self.task_max_runtime_seconds, int)
            or not 1 <= self.task_max_runtime_seconds <= 86_400
            or isinstance(self.task_max_output_bytes, bool)
            or not isinstance(self.task_max_output_bytes, int)
            or not 1_024 <= self.task_max_output_bytes <= 32 * 1024 * 1024
            or isinstance(self.process_memory_bytes, bool)
            or self.process_memory_bytes
            != capability_boundary.PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_PROCESS_MEMORY_BYTES
            or isinstance(self.active_process_limit, bool)
            or self.active_process_limit
            != capability_boundary.PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTOR_ACTIVE_PROCESS_LIMIT
        ):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan budgets are invalid"
            )
        required_true = (
            "product_pilot_started",
            "executor_capability_authenticated",
            "fresh_substrate_revalidated",
            "workspace_snapshot_frozen",
            "workspace_clean",
            "git_runtime_stable",
            "execution_plan_materialized",
            "task_execution_authorized",
            "one_shot_execution_required",
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
                "product-pilot execution plan lacks mandatory evidence"
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
        return {
            name: (
                self.workspace_snapshot.to_dict()
                if name == "workspace_snapshot"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot execution-plan fields mismatch"
            )
        data = dict(value)
        try:
            data["workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
                data["workspace_snapshot"]
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionPlanError(
                "product-pilot workspace snapshot is invalid"
            ) from exc
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutionPlanReceipt,
        *,
        capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            capability,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, capability = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or capability.sha256 != receipt.executor_capability_sha256
        ):
            return None
        live = capability_boundary._get_live_product_pilot_executor_capability_inputs(
            capability
        )
        if live is None:
            return None
        task = live.get("task")
        if type(task) is not DevelopmentTask:
            return None
        try:
            command_spec_sha = _command_spec_sha256(live, receipt.fixed_command_id)
            snapshot, git_runtime_sha = _capture_workspace_snapshot(
                live=live,
                task=task,
            )
        except Exception:
            return None
        checks = (
            (_task_sha256(task), receipt.development_task_sha256),
            (task.base_sha, receipt.development_task_base_sha),
            (command_spec_sha, receipt.command_spec_sha256),
            (live["catalog"].sha256, receipt.catalog_sha256),
            (live["toolchain"].sha256, receipt.toolchain_sha256),
            (live["leased_registry"].lease.sha256, receipt.lease_sha256),
            (
                live["leased_registry"].lease.signed_report_sha256,
                receipt.physical_report_sha256,
            ),
            (
                live["signed_runtime_closure"].sha256,
                receipt.signed_runtime_closure_sha256,
            ),
            (
                live["signed_runtime_closure"].manifest.sha256,
                receipt.runtime_closure_manifest_sha256,
            ),
            (
                live["trusted_git_runtime_receipt"].sha256,
                receipt.trusted_git_runtime_receipt_sha256,
            ),
            (
                live["trusted_git_runtime_receipt"].manifest.sha256,
                receipt.trusted_git_runtime_manifest_sha256,
            ),
            (git_runtime_sha, receipt.git_runtime_evidence_sha256),
            (snapshot.sha256, receipt.workspace_snapshot_sha256),
        )
        if any(left != right for left, right in checks):
            return None
        frozen = dict(live)
        frozen["executor_capability"] = capability
        frozen["workspace_snapshot"] = snapshot
        return frozen

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_execution_plan_authenticated,
    _get_live_product_pilot_execution_plan_inputs,
) = _live_registry()


def _materialize_verified_product_pilot_execution_plan(
    executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
) -> PilotExactTaskProductPilotExecutionPlanReceipt:
    capability, live, task = _require_live_capability(executor_capability)
    snapshot, git_runtime_sha = _capture_workspace_snapshot(live=live, task=task)
    command_spec_sha = _command_spec_sha256(live, capability.fixed_command_id)
    receipt = PilotExactTaskProductPilotExecutionPlanReceipt(
        executor_capability_sha256=capability.sha256,
        execution_admission_sha256=capability.execution_admission_sha256,
        execution_nonce_sha256=capability.execution_nonce_sha256,
        development_task_id=capability.development_task_id,
        development_task_sha256=capability.development_task_sha256,
        development_task_base_sha=capability.development_task_base_sha,
        fixed_command_id=capability.fixed_command_id,
        command_spec_sha256=command_spec_sha,
        repository=capability.repository,
        repository_id=capability.repository_id,
        merge_commit_sha=capability.merge_commit_sha,
        workspace_root_path_sha256=capability.workspace_root_path_sha256,
        catalog_sha256=capability.catalog_sha256,
        toolchain_sha256=capability.toolchain_sha256,
        lease_sha256=capability.lease_sha256,
        physical_report_sha256=capability.physical_report_sha256,
        signed_runtime_closure_sha256=capability.signed_runtime_closure_sha256,
        runtime_closure_manifest_sha256=capability.runtime_closure_manifest_sha256,
        trusted_git_runtime_receipt_sha256=capability.trusted_git_runtime_receipt_sha256,
        trusted_git_runtime_manifest_sha256=capability.trusted_git_runtime_manifest_sha256,
        git_runtime_evidence_sha256=git_runtime_sha,
        workspace_snapshot=snapshot,
        workspace_snapshot_sha256=snapshot.sha256,
        task_max_runtime_seconds=task.budget.max_runtime_seconds,
        task_max_output_bytes=task.budget.max_output_bytes,
        process_memory_bytes=capability.process_memory_bytes,
        active_process_limit=capability.active_process_limit,
    )
    _mark_product_pilot_execution_plan_authenticated(
        receipt,
        capability=capability,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskProductPilotExecutionPlanError(
            "product-pilot execution plan lost live workspace authority"
        )
    return receipt


def materialize_pilot_exact_task_product_pilot_execution_plan(
    executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
) -> PilotExactTaskProductPilotExecutionPlanReceipt:
    """Freeze one clean workspace snapshot and authorize only the next launch boundary."""
    return _materialize_verified_product_pilot_execution_plan(executor_capability)


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_PLAN_SCOPE",
    "PilotExactTaskProductPilotExecutionPlanError",
    "PilotExactTaskProductPilotExecutionPlanReceipt",
    "materialize_pilot_exact_task_product_pilot_execution_plan",
]
