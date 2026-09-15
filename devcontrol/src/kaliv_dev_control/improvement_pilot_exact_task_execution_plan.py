"""ADR-DC-037 exact workspace-snapshot-bound launch plan; this module never executes the pilot task."""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_executor_capability as capability_boundary
from .improvement_pilot_exact_task_executor_capability import (
    PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY,
    PilotExactTaskExecutorCapability,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-plan/v1"
)
PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY = (
    "live-materialized-one-dc-l16-workspace-snapshot-bound-launch-plan-only"
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_MAX_OUTPUT_BYTES = 256 * 1024 * 1024


class PilotExactTaskExecutionPlanError(ValueError):
    """One exact non-executing launch plan could not be materialized safely."""


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


@dataclass(frozen=True, slots=True)
class PilotExactTaskFixedCommandPlan:
    command_id: str
    argv: tuple[str, ...]
    cwd: str
    max_timeout_seconds: int
    max_output_bytes: int
    source_environment_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.command_id, str)
            or _COMMAND_ID.fullmatch(self.command_id) is None
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan command id is invalid"
            )
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or any(
                not isinstance(item, str)
                or not item
                or "\0" in item
                or "\n" in item
                or "\r" in item
                for item in self.argv
            )
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan argv is invalid"
            )
        if not Path(self.argv[0]).is_absolute():
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan executable must be absolute"
            )
        if not isinstance(self.cwd, str):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan cwd is invalid"
            )
        if self.cwd != ".":
            relative = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise PilotExactTaskExecutionPlanError(
                    "fixed command plan cwd is invalid"
                )
        if (
            isinstance(self.max_timeout_seconds, bool)
            or not isinstance(self.max_timeout_seconds, int)
            or not 1 <= self.max_timeout_seconds <= 86_400
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan timeout is invalid"
            )
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 1_024 <= self.max_output_bytes <= _MAX_OUTPUT_BYTES
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan output budget is invalid"
            )
        _hex64(
            self.source_environment_sha256,
            name="fixed command plan source environment sha256",
        )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "max_timeout_seconds": self.max_timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "source_environment_sha256": self.source_environment_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskFixedCommandPlan":
        fields = {
            "command_id",
            "argv",
            "cwd",
            "max_timeout_seconds",
            "max_output_bytes",
            "source_environment_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan fields mismatch"
            )
        argv = value["argv"]
        if not isinstance(argv, list) or any(
            not isinstance(item, str) for item in argv
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan argv must be a string array"
            )
        return cls(
            command_id=value["command_id"],
            argv=tuple(argv),
            cwd=value["cwd"],
            max_timeout_seconds=value["max_timeout_seconds"],
            max_output_bytes=value["max_output_bytes"],
            source_environment_sha256=value["source_environment_sha256"],
        )

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _require_capability_evidence(
    value: Any,
) -> PilotExactTaskExecutorCapability:
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
    return value


def _fixed_command_plan(
    capability: PilotExactTaskExecutorCapability,
    inputs: Mapping[str, Any],
) -> PilotExactTaskFixedCommandPlan:
    try:
        task = inputs["task"]
        template = inputs["leased_registry"].resolve(
            task,
            capability.fixed_command_id,
        )
        return PilotExactTaskFixedCommandPlan(
            command_id=template.command_id,
            argv=tuple(template.argv),
            cwd=template.cwd,
            max_timeout_seconds=min(
                task.budget.max_runtime_seconds,
                template.max_timeout_seconds,
            ),
            max_output_bytes=task.budget.max_output_bytes,
            source_environment_sha256=capability.source_environment_sha256,
        )
    except PilotExactTaskExecutionPlanError:
        raise
    except Exception as exc:
        raise PilotExactTaskExecutionPlanError(
            "fixed Tier-A command plan could not be snapshotted"
        ) from exc


def _validate_workspace_snapshot(
    snapshot: GitWorkspaceSnapshot,
    *,
    base_sha: str,
) -> None:
    if type(snapshot) is not GitWorkspaceSnapshot:
        raise PilotExactTaskExecutionPlanError(
            "exact GitWorkspaceSnapshot is required"
        )
    if snapshot.head_sha != base_sha:
        raise PilotExactTaskExecutionPlanError(
            "workspace snapshot HEAD does not match the exact task base"
        )
    if (
        snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskExecutionPlanError(
            "workspace snapshot must contain no unstaged or untracked state"
        )
    if (
        snapshot.unstaged_patch_sha256 != _EMPTY_SHA256
        or snapshot.untracked_paths_sha256 != _EMPTY_SHA256
    ):
        raise PilotExactTaskExecutionPlanError(
            "empty workspace state carries a non-empty digest"
        )
    if snapshot.staged_patch_bytes == 0:
        if snapshot.staged_patch_sha256 != _EMPTY_SHA256:
            raise PilotExactTaskExecutionPlanError(
                "empty staged patch carries a non-empty digest"
            )
    elif snapshot.staged_patch_sha256 == _EMPTY_SHA256:
        raise PilotExactTaskExecutionPlanError(
            "non-empty staged patch carries the empty digest"
        )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
        ],
    ] = {}

    def mark(
        value: Any,
        capability: PilotExactTaskExecutorCapability,
    ) -> None:
        key = id(value)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            value.sha256,
            weakref.ref(value, cleanup),
            weakref.ref(capability),
        )

    def get(value: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(value))
        if entry is None:
            return None
        pid, digest, ref, capability_ref = entry
        if (
            pid != os.getpid()
            or ref() is not value
            or capability_ref() is not value.executor_capability
        ):
            return None
        try:
            if value.sha256 != digest:
                return None
            fresh = capability_boundary._get_live_capability_inputs(
                value.executor_capability
            )
            if fresh is None:
                return None
            if (
                fresh["admission_receipt"].sha256
                != value.admission_receipt_sha256
                or fresh["admission_receipt"].execution_nonce_sha256
                != value.execution_nonce_sha256
                or fresh["task"].task_id
                != value.executor_capability.development_task_id
                or _fixed_command_plan(
                    value.executor_capability,
                    fresh,
                )
                != value.fixed_command_plan
            ):
                return None
        except Exception:
            return None
        frozen = dict(fresh)
        frozen["workspace_snapshot"] = value.workspace_snapshot
        frozen["fixed_command_plan"] = value.fixed_command_plan
        return MappingProxyType(frozen)

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
    development_task_sha256: str
    fixed_command_id: str
    fixed_command_plan: PilotExactTaskFixedCommandPlan
    fixed_command_plan_sha256: str
    workspace_snapshot: GitWorkspaceSnapshot
    workspace_snapshot_sha256: str
    workspace_head_matches_task_base: bool = True
    workspace_staged_patch_bound: bool = True
    workspace_unstaged_clean: bool = True
    workspace_untracked_clean: bool = True
    fresh_capability_revalidation_required: bool = True
    fresh_snapshot_equality_required: bool = True
    prelaunch_execution_reservation_required: bool = True
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
                "execution plan schema is unsupported"
            )
        capability = _require_capability_evidence(self.executor_capability)
        for name in (
            "executor_capability_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if (
            not isinstance(self.fixed_command_id, str)
            or _COMMAND_ID.fullmatch(self.fixed_command_id) is None
        ):
            raise PilotExactTaskExecutionPlanError(
                "execution plan command id is invalid"
            )
        if type(self.fixed_command_plan) is not PilotExactTaskFixedCommandPlan:
            raise PilotExactTaskExecutionPlanError(
                "execution plan fixed command is invalid"
            )
        task = capability.task_binding.development_task
        expected = {
            "executor_capability_sha256": capability.sha256,
            "admission_receipt_sha256": capability.admission_receipt_sha256,
            "execution_nonce_sha256": capability.execution_nonce_sha256,
            "development_task_sha256": capability.development_task_sha256,
            "fixed_command_id": capability.fixed_command_id,
            "fixed_command_plan_sha256": self.fixed_command_plan.sha256,
            "workspace_snapshot_sha256": self.workspace_snapshot.sha256,
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
            self.fixed_command_plan.command_id != capability.fixed_command_id
            or self.fixed_command_plan.source_environment_sha256
            != capability.source_environment_sha256
            or self.fixed_command_plan.max_output_bytes
            != task.budget.max_output_bytes
        ):
            raise PilotExactTaskExecutionPlanError(
                "fixed command plan is not bound to the executor capability"
            )
        _validate_workspace_snapshot(
            self.workspace_snapshot,
            base_sha=task.base_sha,
        )
        required_true = (
            "workspace_head_matches_task_base",
            "workspace_staged_patch_bound",
            "workspace_unstaged_clean",
            "workspace_untracked_clean",
            "fresh_capability_revalidation_required",
            "fresh_snapshot_equality_required",
            "prelaunch_execution_reservation_required",
            "execution_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskExecutionPlanError(
                "execution plan verification requirements must stay true"
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
                "execution plan authority is unsupported"
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
            "development_task_sha256": self.development_task_sha256,
            "fixed_command_id": self.fixed_command_id,
            "fixed_command_plan": self.fixed_command_plan.to_dict(),
            "fixed_command_plan_sha256": self.fixed_command_plan_sha256,
            "workspace_snapshot": self.workspace_snapshot.to_dict(),
            "workspace_snapshot_sha256": self.workspace_snapshot_sha256,
            "workspace_head_matches_task_base": self.workspace_head_matches_task_base,
            "workspace_staged_patch_bound": self.workspace_staged_patch_bound,
            "workspace_unstaged_clean": self.workspace_unstaged_clean,
            "workspace_untracked_clean": self.workspace_untracked_clean,
            "fresh_capability_revalidation_required": (
                self.fresh_capability_revalidation_required
            ),
            "fresh_snapshot_equality_required": self.fresh_snapshot_equality_required,
            "prelaunch_execution_reservation_required": (
                self.prelaunch_execution_reservation_required
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
        if not isinstance(value, Mapping):
            raise PilotExactTaskExecutionPlanError(
                "execution plan must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskExecutionPlanError(
                "execution plan fields mismatch"
            )
        data = dict(value)
        data["executor_capability"] = (
            PilotExactTaskExecutorCapability.from_mapping(
                data["executor_capability"]
            )
        )
        data["fixed_command_plan"] = PilotExactTaskFixedCommandPlan.from_mapping(
            data["fixed_command_plan"]
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
                "execution plan JSON is invalid"
            ) from exc
        return cls.from_mapping(value)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_exact_task_execution_plan(
    capability: PilotExactTaskExecutorCapability,
) -> PilotExactTaskExecutionPlan:
    """Freeze one exact read-only workspace snapshot; never run the pilot command."""
    durable_capability = _require_capability_evidence(capability)
    inputs = capability_boundary._get_live_capability_inputs(durable_capability)
    if inputs is None:
        raise PilotExactTaskExecutionPlanError(
            "execution plan requires the exact fresh live ADR-DC-036 capability"
        )

    fixed_command_plan = _fixed_command_plan(
        durable_capability,
        inputs,
    )
    try:
        evidence = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        )
        snapshot = evidence.snapshot()
    except Exception as exc:
        raise PilotExactTaskExecutionPlanError(
            "trusted-Git workspace snapshot failed"
        ) from exc

    _validate_workspace_snapshot(
        snapshot,
        base_sha=inputs["task"].base_sha,
    )
    plan = PilotExactTaskExecutionPlan(
        executor_capability=durable_capability,
        executor_capability_sha256=durable_capability.sha256,
        admission_receipt_sha256=durable_capability.admission_receipt_sha256,
        execution_nonce_sha256=durable_capability.execution_nonce_sha256,
        development_task_sha256=durable_capability.development_task_sha256,
        fixed_command_id=durable_capability.fixed_command_id,
        fixed_command_plan=fixed_command_plan,
        fixed_command_plan_sha256=fixed_command_plan.sha256,
        workspace_snapshot=snapshot,
        workspace_snapshot_sha256=snapshot.sha256,
    )
    _mark_live_execution_plan(plan, durable_capability)
    if plan.materialization_authenticated is not True:
        raise PilotExactTaskExecutionPlanError(
            "live execution-plan provenance could not be retained"
        )
    return plan


def materialize_pilot_exact_task_execution_plan(
    capability: PilotExactTaskExecutorCapability,
) -> PilotExactTaskExecutionPlan:
    """Public ADR-DC-037 boundary; all authority comes from the live capability."""
    return _materialize_verified_exact_task_execution_plan(capability)


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY",
    "PilotExactTaskExecutionPlanError",
    "PilotExactTaskFixedCommandPlan",
    "PilotExactTaskExecutionPlan",
    "materialize_pilot_exact_task_execution_plan",
]
