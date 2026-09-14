"""Host-bound ADR-DC-035 mapping from one live pilot admission to DevelopmentTask.

This module materializes only the immutable DevelopmentTask identity selected by a
host-controlled registry. It does not construct a Tier-A command registry, read a
workspace, launch a process, mutate Git, or consume the execution admission.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contract import DevelopmentTask, MergeAuthority
from .improvement_pilot_exact_task_execution_admission import (
    PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY,
    PilotExactTaskExecutionAdmissionReceipt,
)
from .improvement_pilot_exact_task_execution_plan_requirements import (
    PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY,
    PilotExactTaskExecutionPlanRequirements,
)

PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-development-task-registry/v1"
)
PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-development-task-binding/v1"
)
PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY = (
    "host-bound-one-exact-development-task-only"
)
_MAX_REGISTRY_BYTES = 256 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PILOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


class PilotExactTaskDevelopmentTaskBindingError(ValueError):
    """ADR-DC-035 task registry or exact task binding is malformed or unsafe."""


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
        raise PilotExactTaskDevelopmentTaskBindingError(
            "exact-task DevelopmentTask binding is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskDevelopmentTaskBindingError(f"{name} is invalid")
    return value


def _task_sha256(task: DevelopmentTask) -> str:
    if type(task) is not DevelopmentTask:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "exact DevelopmentTask object is required"
        )
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _require_requirements(value: Any) -> PilotExactTaskExecutionPlanRequirements:
    if type(value) is not PilotExactTaskExecutionPlanRequirements:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "exact ADR-DC-034 execution-plan requirements are required"
        )
    try:
        replayed = PilotExactTaskExecutionPlanRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "ADR-DC-034 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "ADR-DC-034 requirements replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY
        or value.live_admission_receipt_required is not True
        or value.host_pinned_task_registry_required is not True
        or value.exact_development_task_required is not True
        or value.selected_pilot_task_mapping_required is not True
        or value.single_fixed_command_required is not True
        or value.execution_plan_materialized is not False
        or value.execution_consumed is not False
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.integration_ready is not False
        or value.product_pilot_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskDevelopmentTaskBindingError(
            "task binding requires one inert ADR-DC-034 requirements artifact"
        )
    return value


def _require_live_receipt(value: Any) -> PilotExactTaskExecutionAdmissionReceipt:
    if type(value) is not PilotExactTaskExecutionAdmissionReceipt:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "exact live ADR-DC-033 admission receipt is required"
        )
    try:
        replayed = PilotExactTaskExecutionAdmissionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "ADR-DC-033 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "ADR-DC-033 receipt replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        or value.task_execution_authorized is not True
        or value.task_execution_started is not False
        or value.execution_consumed is not False
        or value.transaction_authenticated is not True
    ):
        raise PilotExactTaskDevelopmentTaskBindingError(
            "DevelopmentTask binding requires the exact live unconsumed ADR-DC-033 receipt"
        )
    return value


def _require_live_scope(
    requirements: PilotExactTaskExecutionPlanRequirements,
    receipt: PilotExactTaskExecutionAdmissionReceipt,
) -> tuple[PilotExactTaskExecutionPlanRequirements, PilotExactTaskExecutionAdmissionReceipt]:
    req = _require_requirements(requirements)
    live = _require_live_receipt(receipt)
    if (
        req.admission_receipt_sha256 != live.sha256
        or req.execution_nonce_sha256 != live.execution_nonce_sha256
        or req.selected_pilot_task_id != live.selected_pilot_task_id
        or req.workspace_root_path_sha256 != live.workspace_root_path_sha256
        or req.admission_receipt.to_dict() != live.to_dict()
    ):
        raise PilotExactTaskDevelopmentTaskBindingError(
            "ADR-DC-034 requirements are not bound to this exact live ADR-DC-033 receipt"
        )
    return req, live


def _parse_registry_payload(payload: Any) -> tuple[str, dict[str, DevelopmentTask]]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_REGISTRY_BYTES:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry bytes are missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {"schema", "entries"}:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry fields mismatch"
        )
    if value.get("schema") != PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry schema is unsupported"
        )
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list) or not 1 <= len(raw_entries) <= 256:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry entries are invalid"
        )

    canonical_entries: list[dict[str, Any]] = []
    resolved: dict[str, DevelopmentTask] = {}
    task_ids: set[str] = set()
    previous_pilot_id: str | None = None
    for raw in raw_entries:
        if not isinstance(raw, Mapping) or set(raw) != {
            "selected_pilot_task_id",
            "development_task",
            "development_task_sha256",
        }:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry entry fields mismatch"
            )
        pilot_id = raw.get("selected_pilot_task_id")
        if not isinstance(pilot_id, str) or _PILOT_ID.fullmatch(pilot_id) is None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry pilot task id is invalid"
            )
        if previous_pilot_id is not None and pilot_id <= previous_pilot_id:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry entries must be sorted and unique"
            )
        previous_pilot_id = pilot_id
        try:
            task = DevelopmentTask.from_mapping(raw.get("development_task"))
        except Exception as exc:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry contains an invalid DevelopmentTask"
            ) from exc
        digest = _task_sha256(task)
        if raw.get("development_task_sha256") != digest:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry DevelopmentTask SHA-256 mismatch"
            )
        if task.task_id in task_ids:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry DevelopmentTask ids must be unique"
            )
        task_ids.add(task.task_id)
        if (
            task.merge_authority is not MergeAuthority.HUMAN
            or len(task.allowed_command_ids) != 1
            or task.required_tests != task.allowed_command_ids
        ):
            raise PilotExactTaskDevelopmentTaskBindingError(
                "host task registry task is not one fixed human-merge command"
            )
        resolved[pilot_id] = task
        canonical_entries.append(
            {
                "selected_pilot_task_id": pilot_id,
                "development_task": task.to_dict(),
                "development_task_sha256": digest,
            }
        )

    canonical = {
        "schema": PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA,
        "entries": canonical_entries,
    }
    canonical_bytes = _canonical(canonical).encode("utf-8")
    if payload != canonical_bytes:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host task registry is not canonical JSON"
        )
    return hashlib.sha256(payload).hexdigest(), resolved


@dataclass(frozen=True, slots=True)
class PilotExactTaskDevelopmentTaskBinding:
    plan_requirements: PilotExactTaskExecutionPlanRequirements
    plan_requirements_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    registry_sha256: str
    selected_pilot_task_id: str
    development_task: DevelopmentTask
    development_task_id: str
    development_task_sha256: str
    fixed_command_id: str
    repository: str
    base_sha: str
    requested_main_sha: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    host_registry_verified: bool = True
    pilot_task_mapping_verified: bool = True
    development_task_materialized: bool = True
    single_fixed_command_verified: bool = True
    execution_plan_materialized: bool = False
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
    authority: str = PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
    schema: str = PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding schema unsupported"
            )
        requirements = _require_requirements(self.plan_requirements)
        if type(self.development_task) is not DevelopmentTask:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding requires an exact DevelopmentTask"
            )
        for name in (
            "plan_requirements_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "registry_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if not isinstance(self.selected_pilot_task_id, str) or _PILOT_ID.fullmatch(self.selected_pilot_task_id) is None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "selected_pilot_task_id is invalid"
            )
        if not isinstance(self.development_task_id, str) or _TASK_ID.fullmatch(self.development_task_id) is None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "development_task_id is invalid"
            )
        if not isinstance(self.fixed_command_id, str) or _COMMAND_ID.fullmatch(self.fixed_command_id) is None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "fixed_command_id is invalid"
            )
        if not isinstance(self.base_sha, str) or _HEX40.fullmatch(self.base_sha) is None:
            raise PilotExactTaskDevelopmentTaskBindingError("base_sha is invalid")
        if not isinstance(self.requested_main_sha, str) or _HEX40.fullmatch(self.requested_main_sha) is None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "requested_main_sha is invalid"
            )
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskDevelopmentTaskBindingError("repository is unsupported")
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "local commit human scope must be boolean"
            )
        task = self.development_task
        expected = {
            "plan_requirements_sha256": requirements.sha256,
            "admission_receipt_sha256": requirements.admission_receipt_sha256,
            "execution_nonce_sha256": requirements.execution_nonce_sha256,
            "selected_pilot_task_id": requirements.selected_pilot_task_id,
            "development_task_id": task.task_id,
            "development_task_sha256": _task_sha256(task),
            "fixed_command_id": task.allowed_command_ids[0] if len(task.allowed_command_ids) == 1 else None,
            "repository": requirements.repository,
            "base_sha": requirements.base_sha,
            "requested_main_sha": requirements.requested_main_sha,
            "workspace_root_path_sha256": requirements.workspace_root_path_sha256,
            "local_commits_allowed_by_human_scope": requirements.local_commits_allowed_by_human_scope,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskDevelopmentTaskBindingError(
                f"DevelopmentTask binding identity mismatch: {mismatch}"
            )
        if (
            task.repository != requirements.repository
            or task.base_sha != requirements.base_sha
            or task.merge_authority is not MergeAuthority.HUMAN
            or len(task.allowed_command_ids) != 1
            or task.required_tests != task.allowed_command_ids
        ):
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask does not satisfy exact execution-plan task requirements"
            )
        required_true = (
            "host_registry_verified",
            "pilot_task_mapping_verified",
            "development_task_materialized",
            "single_fixed_command_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding verification flags must stay true"
            )
        forced_false = (
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
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding authority invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskDevelopmentTaskBinding":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding fields mismatch"
            )
        data = dict(value)
        try:
            data["plan_requirements"] = PilotExactTaskExecutionPlanRequirements.from_mapping(
                data["plan_requirements"]
            )
            data["development_task"] = DevelopmentTask.from_mapping(data["development_task"])
        except Exception as exc:
            raise PilotExactTaskDevelopmentTaskBindingError(
                "DevelopmentTask binding nested evidence is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            if name == "plan_requirements":
                result[name] = self.plan_requirements.to_dict()
            elif name == "development_task":
                result[name] = self.development_task.to_dict()
            else:
                result[name] = getattr(self, name)
        return result

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _bind_verified_development_task(
    *,
    plan_requirements: PilotExactTaskExecutionPlanRequirements,
    admission_receipt: PilotExactTaskExecutionAdmissionReceipt,
    registry_payload: bytes,
) -> PilotExactTaskDevelopmentTaskBinding:
    requirements, _ = _require_live_scope(plan_requirements, admission_receipt)
    registry_sha256, entries = _parse_registry_payload(registry_payload)
    try:
        task = entries[requirements.selected_pilot_task_id]
    except KeyError as exc:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "selected pilot task is absent from the host-pinned task registry"
        ) from exc
    if task.repository != requirements.repository or task.base_sha != requirements.base_sha:
        raise PilotExactTaskDevelopmentTaskBindingError(
            "host-pinned DevelopmentTask repository/base does not match signed pilot scope"
        )
    command_id = task.allowed_command_ids[0]
    return PilotExactTaskDevelopmentTaskBinding(
        plan_requirements=requirements,
        plan_requirements_sha256=requirements.sha256,
        admission_receipt_sha256=requirements.admission_receipt_sha256,
        execution_nonce_sha256=requirements.execution_nonce_sha256,
        registry_sha256=registry_sha256,
        selected_pilot_task_id=requirements.selected_pilot_task_id,
        development_task=task,
        development_task_id=task.task_id,
        development_task_sha256=_task_sha256(task),
        fixed_command_id=command_id,
        repository=requirements.repository,
        base_sha=requirements.base_sha,
        requested_main_sha=requirements.requested_main_sha,
        workspace_root_path_sha256=requirements.workspace_root_path_sha256,
        local_commits_allowed_by_human_scope=(
            requirements.local_commits_allowed_by_human_scope
        ),
    )


def bind_pilot_exact_task_development_task(*args: Any, **kwargs: Any) -> PilotExactTaskDevelopmentTaskBinding:
    raise PilotExactTaskDevelopmentTaskBindingError(
        "production host-pinned DevelopmentTask binding boundary is not installed"
    )
