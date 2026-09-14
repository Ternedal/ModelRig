"""ADR-DC-037 freezes one exact pre-execution workspace plan without running the task.

This boundary is intentionally narrower than the low-level TierALaunchPlan. It
captures the exact Git workspace state that ADR-DC-034 requires while retaining
the already-verified ADR-DC-036 capability as process-local authority. The
existing Tier-A receipt orchestrator remains the only later task execution path;
no runtime closure is staged and no pilot command is started here.
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
from .improvement_pilot_exact_task_executor_capability import (
    PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY,
    PilotExactTaskExecutorCapability,
    _get_live_capability_inputs,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence
from .trusted_git_runtime_runner import TrustedGitRunner

PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-plan/v1"
)
PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY = (
    "live-materialized-one-dc-l16-exact-task-execution-plan-only"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


class PilotExactTaskExecutionPlanError(ValueError):
    """One exact ADR-DC-037 pre-execution plan could not be frozen safely."""


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
        raise PilotExactTaskExecutionPlanError(
            "exact-task execution plan is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskExecutionPlanError(f"{name} is invalid")
    return value


def _require_capability(
    value: Any,
    *,
    live: bool,
) -> tuple[PilotExactTaskExecutorCapability, Mapping[str, Any] | None]:
    if type(value) is not PilotExactTaskExecutorCapability:
        raise PilotExactTaskExecutionPlanError(
            "exact ADR-DC-036 executor capability is required"
        )
    try:
        replayed = PilotExactTaskExecutorCapability.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutionPlanError(
            "ADR-DC-036 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionPlanError(
            "ADR-DC-036 capability replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY
        or value.executor_capability_materialized is not True
        or value.physical_isolation_verified is not True
        or value.runtime_closure_verified is not True
        or value.trusted_git_runtime_verified is not True
        or value.workspace_identity_verified is not True
        or value.control_plane_toolhost_verified is not True
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
        raise PilotExactTaskExecutionPlanError(
            "execution plan requires one inert verified ADR-DC-036 capability"
        )
    inputs = _get_live_capability_inputs(value) if live else None
    if live and inputs is None:
        raise PilotExactTaskExecutionPlanError(
            "execution plan requires the exact live ADR-DC-036 capability"
        )
    return value, inputs


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], dict[str, Any]],
    ] = {}

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

    def get(value: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(value))
        if entry is None:
            return None
        pid, digest, ref, inputs = entry
        if pid != os.getpid() or ref() is not value:
            return None
        try:
            if value.sha256 != digest:
                return None
            capability = inputs["executor_capability"]
            if capability is not value.executor_capability:
                return None
            live_inputs = _get_live_capability_inputs(capability)
            if live_inputs is None:
                return None
            if (
                capability.sha256 != value.executor_capability_sha256
                or capability.execution_nonce_sha256 != value.execution_nonce_sha256
                or live_inputs["task"].task_id != value.development_task_id
                or live_inputs["git_runner"].runtime.receipt.sha256
                != value.trusted_git_runtime_receipt_sha256
            ):
                return None
        except Exception:
            return None
        return inputs

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_live_execution_plan, _get_live_execution_plan_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskExecutionPlan:
    executor_capability: PilotExactTaskExecutorCapability
    executor_capability_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    fixed_command_id: str
    trusted_git_runtime_receipt_sha256: str
    workspace_snapshot: GitWorkspaceSnapshot
    workspace_snapshot_sha256: str
    workspace_head_sha: str
    executor_capability_materialized: bool = True
    workspace_snapshot_verified: bool = True
    workspace_head_verified: bool = True
    workspace_unstaged_and_untracked_absent: bool = True
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA:
            raise PilotExactTaskExecutionPlanError(
                "exact-task execution plan schema is unsupported"
            )
        capability, _ = _require_capability(self.executor_capability, live=False)
        for name in (
            "executor_capability_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "trusted_git_runtime_receipt_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if (
            not isinstance(self.workspace_head_sha, str)
            or _HEX40.fullmatch(self.workspace_head_sha) is None
        ):
            raise PilotExactTaskExecutionPlanError("workspace_head_sha is invalid")
        if (
            not isinstance(self.development_task_id, str)
            or _TASK_ID.fullmatch(self.development_task_id) is None
        ):
            raise PilotExactTaskExecutionPlanError(
                "execution plan DevelopmentTask id is invalid"
            )
        if (
            not isinstance(self.fixed_command_id, str)
            or _COMMAND_ID.fullmatch(self.fixed_command_id) is None
        ):
            raise PilotExactTaskExecutionPlanError(
                "execution plan command id is invalid"
            )
        if type(self.workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskExecutionPlanError(
                "exact GitWorkspaceSnapshot is required"
            )
        try:
            replayed_snapshot = GitWorkspaceSnapshot.from_mapping(
                self.workspace_snapshot.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskExecutionPlanError(
                "workspace snapshot replay validation failed"
            ) from exc
        if replayed_snapshot != self.workspace_snapshot:
            raise PilotExactTaskExecutionPlanError(
                "workspace snapshot replay identity mismatch"
            )

        expected = {
            "executor_capability_sha256": capability.sha256,
            "admission_receipt_sha256": capability.admission_receipt_sha256,
            "execution_nonce_sha256": capability.execution_nonce_sha256,
            "development_task_id": capability.development_task_id,
            "development_task_sha256": capability.development_task_sha256,
            "fixed_command_id": capability.fixed_command_id,
            "trusted_git_runtime_receipt_sha256": (
                capability.trusted_git_runtime_receipt_sha256
            ),
            "workspace_snapshot_sha256": self.workspace_snapshot.sha256,
            "workspace_head_sha": capability.task_binding.base_sha,
        }
        mismatch = next(
            (
                name
                for name, expected_value in expected.items()
                if getattr(self, name) != expected_value
            ),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionPlanError(
                f"execution plan identity mismatch: {mismatch}"
            )
        if (
            self.workspace_snapshot.head_sha != self.workspace_head_sha
            or self.workspace_snapshot.has_unstaged_or_untracked
        ):
            raise PilotExactTaskExecutionPlanError(
                "workspace snapshot is not an exact-base staged-only input"
            )

        required_true = (
            "executor_capability_materialized",
            "workspace_snapshot_verified",
            "workspace_head_verified",
            "workspace_unstaged_and_untracked_absent",
            "execution_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskExecutionPlanError(
                "execution plan verification flags must stay true"
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
            raise PilotExactTaskExecutionPlanError(
                "execution plan cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY:
            raise PilotExactTaskExecutionPlanError(
                "exact-task execution plan authority is unsupported"
            )

    @property
    def materialization_authenticated(self) -> bool:
        return _get_live_execution_plan_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "executor_capability": self.executor_capability.to_dict(),
            "executor_capability_sha256": self.executor_capability_sha256,
            "admission_receipt_sha256": self.admission_receipt_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "development_task_id": self.development_task_id,
            "development_task_sha256": self.development_task_sha256,
            "fixed_command_id": self.fixed_command_id,
            "trusted_git_runtime_receipt_sha256": (
                self.trusted_git_runtime_receipt_sha256
            ),
            "workspace_snapshot": self.workspace_snapshot.to_dict(),
            "workspace_snapshot_sha256": self.workspace_snapshot_sha256,
            "workspace_head_sha": self.workspace_head_sha,
            "executor_capability_materialized": self.executor_capability_materialized,
            "workspace_snapshot_verified": self.workspace_snapshot_verified,
            "workspace_head_verified": self.workspace_head_verified,
            "workspace_unstaged_and_untracked_absent": (
                self.workspace_unstaged_and_untracked_absent
            ),
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
            "production_activation_authorized": (
                self.production_activation_authorized
            ),
            "authority": self.authority,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutionPlan":
        fields = {
            "schema",
            "executor_capability",
            "executor_capability_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_id",
            "development_task_sha256",
            "fixed_command_id",
            "trusted_git_runtime_receipt_sha256",
            "workspace_snapshot",
            "workspace_snapshot_sha256",
            "workspace_head_sha",
            "executor_capability_materialized",
            "workspace_snapshot_verified",
            "workspace_head_verified",
            "workspace_unstaged_and_untracked_absent",
            "execution_plan_materialized",
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
            "authority",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise PilotExactTaskExecutionPlanError(
                "exact-task execution plan fields mismatch"
            )
        data = dict(value)
        data["executor_capability"] = PilotExactTaskExecutorCapability.from_mapping(
            data["executor_capability"]
        )
        data["workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
            data["workspace_snapshot"]
        )
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskExecutionPlan":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskExecutionPlanError(
                "exact-task execution plan JSON is invalid"
            ) from exc
        return cls.from_mapping(value)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def materialize_pilot_exact_task_execution_plan(
    executor_capability: PilotExactTaskExecutorCapability,
) -> PilotExactTaskExecutionPlan:
    """Freeze exact trusted-Git workspace state without starting the task."""
    capability, live_inputs = _require_capability(executor_capability, live=True)
    assert live_inputs is not None

    task = live_inputs.get("task")
    git_runner = live_inputs.get("git_runner")
    workspace_root = live_inputs.get("workspace_root")
    if type(task) is not DevelopmentTask:
        raise PilotExactTaskExecutionPlanError(
            "live executor capability lost its exact DevelopmentTask"
        )
    if type(git_runner) is not TrustedGitRunner:
        raise PilotExactTaskExecutionPlanError(
            "live executor capability lost its TrustedGitRunner"
        )
    if workspace_root is None:
        raise PilotExactTaskExecutionPlanError(
            "live executor capability lost its workspace root"
        )

    try:
        git_runner.runtime.verify()
        runtime_receipt_sha256 = git_runner.runtime.receipt.sha256
        if runtime_receipt_sha256 != capability.trusted_git_runtime_receipt_sha256:
            raise PilotExactTaskExecutionPlanError(
                "trusted Git runtime identity changed before workspace snapshot"
            )
        evidence = _GitWorkspaceEvidence(workspace_root, task, git_runner)
        snapshot = evidence.snapshot()
        git_runner.runtime.verify()
    except PilotExactTaskExecutionPlanError:
        raise
    except Exception as exc:
        raise PilotExactTaskExecutionPlanError(
            "trusted Git workspace snapshot failed"
        ) from exc

    if git_runner.runtime.receipt.sha256 != runtime_receipt_sha256:
        raise PilotExactTaskExecutionPlanError(
            "trusted Git runtime identity changed during workspace snapshot"
        )
    if snapshot.head_sha != task.base_sha:
        raise PilotExactTaskExecutionPlanError(
            "workspace HEAD does not match the exact DevelopmentTask base"
        )
    if snapshot.has_unstaged_or_untracked:
        raise PilotExactTaskExecutionPlanError(
            "workspace must contain only an optional staged patch before execution"
        )

    plan = PilotExactTaskExecutionPlan(
        executor_capability=capability,
        executor_capability_sha256=capability.sha256,
        admission_receipt_sha256=capability.admission_receipt_sha256,
        execution_nonce_sha256=capability.execution_nonce_sha256,
        development_task_id=capability.development_task_id,
        development_task_sha256=capability.development_task_sha256,
        fixed_command_id=capability.fixed_command_id,
        trusted_git_runtime_receipt_sha256=runtime_receipt_sha256,
        workspace_snapshot=snapshot,
        workspace_snapshot_sha256=snapshot.sha256,
        workspace_head_sha=snapshot.head_sha,
    )
    _mark_live_execution_plan(
        plan,
        {
            "executor_capability": capability,
            "capability_inputs": live_inputs,
            "task": task,
            "git_runner": git_runner,
            "workspace_root": workspace_root,
            "workspace_snapshot": snapshot,
        },
    )
    if plan.materialization_authenticated is not True:
        raise PilotExactTaskExecutionPlanError(
            "live execution-plan provenance could not be retained"
        )
    return plan


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY",
    "PilotExactTaskExecutionPlanError",
    "PilotExactTaskExecutionPlan",
    "materialize_pilot_exact_task_execution_plan",
]
