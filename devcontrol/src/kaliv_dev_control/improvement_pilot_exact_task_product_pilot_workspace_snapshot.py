"""ADR-DC-106 product-pilot exact Git workspace snapshot boundary.

Consumes one live ADR-DC-105 executor capability, revalidates that capability's
Tier-A substrate, and freezes the exact GitWorkspaceSnapshot that the next
execution-plan boundary must bind.

This boundary runs only trusted read-only Git evidence commands. It does not
build a launch plan, stage a runtime closure, start the reviewed command, mutate
Git, write remotely, or grant commit/push/PR/release/deploy authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from typing import Any, Mapping

from . import improvement_pilot_exact_task_product_pilot_executor_capability as capability_boundary
from .contract import DevelopmentTask
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID
from .tier_a_command_receipt import (
    GitWorkspaceSnapshot,
    TierACommandReceiptError,
    _GitWorkspaceEvidence,
)

PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-workspace-snapshot/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_AUTHORITY = (
    "live-product-pilot-fresh-tier-a-git-workspace-snapshot-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCOPE = (
    "started-product-pilot-reviewed-version-check-workspace-snapshot-only-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PilotExactTaskProductPilotWorkspaceSnapshotError(ValueError):
    """The product pilot cannot freeze one safe exact workspace snapshot."""


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
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "product-pilot workspace snapshot is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(f"{name} is invalid")
    return value


def _require_live_capability(value: Any):
    if (
        type(value)
        is not capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt
        or value.executor_capability_materialized is not True
        or value.fresh_substrate_revalidation_required is not True
        or value.fresh_workspace_snapshot_required is not True
        or value.execution_plan_materialization_authorized is not True
        or value.execution_plan_materialized is not False
        or value.task_execution_authorized is not False
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
        or value.next_boundary_execution_plan_required is not True
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "live inert ADR-DC-105 executor capability is required"
        )
    live = capability_boundary._get_live_product_pilot_executor_capability_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "ADR-DC-105 live executor-capability provenance is unavailable"
        )
    task = live.get("task")
    if (
        type(task) is not DevelopmentTask
        or task.task_id != value.development_task_id
        or task.base_sha != value.development_task_base_sha
        or live.get("task_sha256") != value.development_task_sha256
        or task.allowed_command_ids != (value.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
        or value.fixed_command_id != VERSION_CHECK_COMMAND_ID
    ):
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "ADR-DC-105 DevelopmentTask provenance is inconsistent"
        )
    return value, live, task


def _capture_workspace_snapshot(
    *,
    live: Mapping[str, Any],
    task: DevelopmentTask,
) -> GitWorkspaceSnapshot:
    try:
        evidence = _GitWorkspaceEvidence(
            live["workspace_root"],
            task,
            live["git_runner"],
        )
        snapshot = evidence.snapshot()
    except (KeyError, TierACommandReceiptError) as exc:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "trusted Git workspace snapshot capture failed"
        ) from exc
    if snapshot.head_sha != task.base_sha:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "workspace HEAD does not match the exact product-pilot task base"
        )
    if snapshot.has_unstaged_or_untracked:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "workspace snapshot contains unstaged or untracked material"
        )
    return snapshot


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotWorkspaceSnapshotReceipt:
    executor_capability_sha256: str
    execution_admission_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    workspace_root_path_sha256: str
    workspace_root_authority_sha256: str
    catalog_sha256: str
    toolchain_sha256: str
    lease_sha256: str
    signed_runtime_closure_sha256: str
    trusted_git_runtime_receipt_sha256: str
    trusted_git_runtime_manifest_sha256: str
    toolhost_sha256: str
    source_environment_sha256: str
    workspace_snapshot_sha256: str
    workspace_snapshot: GitWorkspaceSnapshot
    product_pilot_started: bool = True
    executor_capability_authenticated: bool = True
    fresh_substrate_revalidated: bool = True
    workspace_snapshot_materialized: bool = True
    workspace_head_matches_task_base: bool = True
    workspace_has_unstaged_or_untracked: bool = False
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
    snapshot_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_AUTHORITY
            or self.snapshot_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCOPE
        ):
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot identity is unsupported"
            )
        for name in (
            "executor_capability_sha256",
            "execution_admission_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
            "workspace_root_authority_sha256",
            "catalog_sha256",
            "toolchain_sha256",
            "lease_sha256",
            "signed_runtime_closure_sha256",
            "trusted_git_runtime_receipt_sha256",
            "trusted_git_runtime_manifest_sha256",
            "toolhost_sha256",
            "source_environment_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        if self.fixed_command_id != VERSION_CHECK_COMMAND_ID:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot command is not the reviewed command"
            )
        if type(self.workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot evidence is invalid"
            )
        if self.workspace_snapshot.sha256 != self.workspace_snapshot_sha256:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot hash is inconsistent"
            )
        if self.workspace_snapshot.head_sha != self.development_task_base_sha:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot is not at the exact task base"
            )
        if self.workspace_snapshot.has_unstaged_or_untracked:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot contains unsafe working-tree state"
            )

        required_true = (
            "product_pilot_started",
            "executor_capability_authenticated",
            "fresh_substrate_revalidated",
            "workspace_snapshot_materialized",
            "workspace_head_matches_task_base",
            "execution_plan_materialization_authorized",
            "next_boundary_execution_plan_required",
        )
        forced_false = (
            "workspace_has_unstaged_or_untracked",
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
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot lacks mandatory evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot grants premature execution authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def snapshot_authenticated(self) -> bool:
        return _get_live_product_pilot_workspace_snapshot_inputs(self) is not None

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
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot fields mismatch"
            )
        raw = dict(value)
        try:
            raw["workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
                raw["workspace_snapshot"]
            )
        except TierACommandReceiptError as exc:
            raise PilotExactTaskProductPilotWorkspaceSnapshotError(
                "product-pilot workspace snapshot evidence is invalid"
            ) from exc
        return cls(**raw)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotWorkspaceSnapshotReceipt,
        *,
        executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            executor_capability,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, executor_capability = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or executor_capability.sha256 != receipt.executor_capability_sha256
        ):
            return None
        live = capability_boundary._get_live_product_pilot_executor_capability_inputs(
            executor_capability
        )
        if live is None:
            return None
        task = live.get("task")
        if type(task) is not DevelopmentTask:
            return None
        try:
            fresh = _capture_workspace_snapshot(live=live, task=task)
        except Exception:
            return None
        leased = live.get("leased_registry")
        closure = live.get("signed_runtime_closure")
        git_receipt = live.get("trusted_git_runtime_receipt")
        checks = (
            (live.get("task_sha256"), receipt.development_task_sha256),
            (task.base_sha, receipt.development_task_base_sha),
            (fresh.sha256, receipt.workspace_snapshot_sha256),
            (live.get("workspace_root_path_sha256"), receipt.workspace_root_path_sha256),
            (
                live.get("workspace_root_authority_sha256"),
                receipt.workspace_root_authority_sha256,
            ),
            (getattr(live.get("catalog"), "sha256", None), receipt.catalog_sha256),
            (getattr(live.get("toolchain"), "sha256", None), receipt.toolchain_sha256),
            (getattr(getattr(leased, "lease", None), "sha256", None), receipt.lease_sha256),
            (getattr(closure, "sha256", None), receipt.signed_runtime_closure_sha256),
            (getattr(git_receipt, "sha256", None), receipt.trusted_git_runtime_receipt_sha256),
            (
                getattr(getattr(git_receipt, "manifest", None), "sha256", None),
                receipt.trusted_git_runtime_manifest_sha256,
            ),
            (live.get("toolhost_sha256"), receipt.toolhost_sha256),
            (live.get("source_environment_sha256"), receipt.source_environment_sha256),
        )
        if any(left != right for left, right in checks):
            return None
        frozen = dict(live)
        frozen["executor_capability"] = executor_capability
        frozen["workspace_snapshot"] = fresh
        return frozen

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_workspace_snapshot_authenticated,
    _get_live_product_pilot_workspace_snapshot_inputs,
) = _live_registry()


def materialize_pilot_exact_task_product_pilot_workspace_snapshot(
    executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
) -> PilotExactTaskProductPilotWorkspaceSnapshotReceipt:
    """Freeze the exact read-only Git state required before plan materialization."""
    capability, live, task = _require_live_capability(executor_capability)
    snapshot = _capture_workspace_snapshot(live=live, task=task)
    leased = live["leased_registry"]
    closure = live["signed_runtime_closure"]
    git_receipt = live["trusted_git_runtime_receipt"]
    receipt = PilotExactTaskProductPilotWorkspaceSnapshotReceipt(
        executor_capability_sha256=capability.sha256,
        execution_admission_sha256=capability.execution_admission_sha256,
        execution_nonce_sha256=capability.execution_nonce_sha256,
        development_task_id=capability.development_task_id,
        development_task_sha256=capability.development_task_sha256,
        development_task_base_sha=capability.development_task_base_sha,
        fixed_command_id=capability.fixed_command_id,
        workspace_root_path_sha256=capability.workspace_root_path_sha256,
        workspace_root_authority_sha256=capability.workspace_root_authority_sha256,
        catalog_sha256=capability.catalog_sha256,
        toolchain_sha256=capability.toolchain_sha256,
        lease_sha256=leased.lease.sha256,
        signed_runtime_closure_sha256=closure.sha256,
        trusted_git_runtime_receipt_sha256=git_receipt.sha256,
        trusted_git_runtime_manifest_sha256=git_receipt.manifest.sha256,
        toolhost_sha256=capability.toolhost_sha256,
        source_environment_sha256=capability.source_environment_sha256,
        workspace_snapshot_sha256=snapshot.sha256,
        workspace_snapshot=snapshot,
    )
    _mark_product_pilot_workspace_snapshot_authenticated(
        receipt,
        executor_capability=capability,
    )
    if receipt.snapshot_authenticated is not True:
        raise PilotExactTaskProductPilotWorkspaceSnapshotError(
            "product-pilot workspace snapshot lost live Git provenance"
        )
    return receipt


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_WORKSPACE_SNAPSHOT_SCOPE",
    "PilotExactTaskProductPilotWorkspaceSnapshotError",
    "PilotExactTaskProductPilotWorkspaceSnapshotReceipt",
    "materialize_pilot_exact_task_product_pilot_workspace_snapshot",
]
