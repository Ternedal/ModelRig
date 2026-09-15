"""ADR-DC-041 exact local-commit candidate plan materialization.

This boundary accepts only the exact live favorable ADR-DC-040 mechanical
post-execution evaluation, fresh-rechecks the exact staged candidate twice, and
materializes deterministic local-commit intent. It does not write Git objects,
create a commit, move a local ref, publish remotely, or grant any such authority.

Author/committer identity, commit-object/tree identity, and one-shot write
authorization are deliberately deferred to later host-controlled boundaries.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .contract import DevelopmentTask, normalize_repo_path
from . import improvement_pilot_exact_task_post_execution_evaluation as evaluation_boundary
from .improvement_pilot_exact_task_post_execution_evaluation import (
    PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY,
    PilotExactTaskPostExecutionEvaluationReceipt,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-plan/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-local-commit-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCOPE = "local-commit-candidate-plan-only-v1"
PILOT_EXACT_TASK_LOCAL_COMMIT_OPERATION = (
    "create-one-local-commit-from-exact-staged-candidate-v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_MESSAGE_POLICY = (
    "deterministic-task-id-subject-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitPlanError(ValueError):
    """The evaluated candidate cannot become an inert exact local-commit plan."""


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
        raise PilotExactTaskLocalCommitPlanError(
            "local commit plan is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitPlanError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _development_task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _commit_subject(task_id: str) -> str:
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise PilotExactTaskLocalCommitPlanError("task_id is invalid")
    slug = task_id.lower().replace("_", "-")
    subject = f"rsi: apply {slug}"
    if (
        not subject
        or subject.strip() != subject
        or "\n" in subject
        or "\r" in subject
        or "\x00" in subject
        or len(subject.encode("utf-8")) > 100
    ):
        raise PilotExactTaskLocalCommitPlanError(
            "deterministic local commit subject is invalid"
        )
    return subject


def _require_live_post_execution_evaluation(
    value: Any,
) -> tuple[PilotExactTaskPostExecutionEvaluationReceipt, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskPostExecutionEvaluationReceipt:
        raise PilotExactTaskLocalCommitPlanError(
            "exact ADR-DC-040 post-execution evaluation receipt is required"
        )
    try:
        replayed = PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitPlanError(
            "ADR-DC-040 evaluation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitPlanError(
            "ADR-DC-040 evaluation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.execution_transaction_authenticated is not True
        or value.task_execution_completed is not True
        or value.task_execution_passed is not True
        or value.post_execution_workspace_matched is not True
        or value.candidate_patch_bound is not True
        or value.candidate_patch_present is not True
        or value.scope_policy_passed is not True
        or value.required_tests_satisfied is not True
        or value.mechanical_evaluation_passed is not True
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitPlanError(
            "local commit planning requires one live favorable ADR-DC-040 evaluation"
        )

    inputs = evaluation_boundary._get_live_post_execution_evaluation_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitPlanError(
            "ADR-DC-040 live evaluation inputs are unavailable"
        )
    task = inputs.get("task")
    execution = inputs.get("execution_transaction")
    if (
        type(task) is not DevelopmentTask
        or execution is None
        or _development_task_sha256(task) != value.development_task_sha256
        or getattr(execution, "sha256", None) != value.execution_transaction_sha256
        or getattr(execution, "tier_a_receipt_sha256", None)
        != value.tier_a_receipt_sha256
        or getattr(execution, "execution_nonce_sha256", None)
        != value.execution_nonce_sha256
        or task.task_id != value.task_id
        or task.base_sha != value.base_sha
        or tuple(task.required_tests) != value.required_tests
    ):
        raise PilotExactTaskLocalCommitPlanError(
            "ADR-DC-040 evaluation is not bound to its exact live task"
        )
    return value, inputs


def _fresh_workspace_snapshot(inputs: Mapping[str, Any]) -> GitWorkspaceSnapshot:
    try:
        evidence = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        )
        return evidence.snapshot()
    except Exception as exc:
        raise PilotExactTaskLocalCommitPlanError(
            "fresh local-commit-plan Trusted-Git snapshot failed"
        ) from exc


def _require_snapshot_matches_evaluation(
    evaluation: PilotExactTaskPostExecutionEvaluationReceipt,
    snapshot: GitWorkspaceSnapshot,
) -> None:
    if (
        snapshot != evaluation.post_execution_workspace_snapshot
        or snapshot.sha256 != evaluation.post_execution_workspace_snapshot_sha256
        or snapshot.head_sha != evaluation.base_sha
        or snapshot.staged_patch_sha256 != evaluation.candidate_patch_sha256
        or snapshot.staged_patch_bytes != evaluation.candidate_patch_bytes
        or snapshot.staged_patch_bytes <= 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskLocalCommitPlanError(
            "fresh workspace no longer matches the evaluated staged candidate"
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
        plan: Any,
        evaluation: PilotExactTaskPostExecutionEvaluationReceipt,
    ) -> None:
        key = id(plan)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            plan.sha256,
            weakref.ref(plan, cleanup),
            weakref.ref(evaluation),
        )

    def get(plan: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(plan))
        if entry is None:
            return None
        pid, digest, plan_ref, evaluation_ref = entry
        evaluation = evaluation_ref()
        if (
            pid != os.getpid()
            or plan_ref() is not plan
            or evaluation is None
            or evaluation.evaluation_authenticated is not True
            or plan.sha256 != digest
            or plan.post_execution_evaluation_sha256 != evaluation.sha256
        ):
            return None
        inputs = evaluation_boundary._get_live_post_execution_evaluation_inputs(
            evaluation
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["post_execution_evaluation"] = evaluation
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_local_commit_plan_authenticated,
    _get_live_local_commit_plan_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitPlan:
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    fixed_command_plan_sha256: str
    post_execution_workspace_snapshot: GitWorkspaceSnapshot
    post_execution_workspace_snapshot_sha256: str
    candidate_patch_sha256: str
    candidate_patch_bytes: int
    candidate_numstat_sha256: str
    changed_paths: tuple[str, ...]
    changed_file_count: int
    added_lines: int
    deleted_lines: int
    scope_policy_sha256: str
    executed_command_id: str
    required_tests: tuple[str, ...]
    commit_operation: str
    commit_message_policy: str
    commit_subject: str
    commit_subject_sha256: str
    evaluated_at_utc: str
    planned_at_utc: str
    post_execution_evaluation_authenticated: bool = True
    mechanical_evaluation_passed: bool = True
    fresh_workspace_snapshot_matched: bool = True
    candidate_patch_bound: bool = True
    commit_plan_materialized: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    plan_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCHEMA:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan schema is unsupported"
            )
        if self.plan_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCOPE:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan scope is unsupported"
            )
        for name in (
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "post_execution_workspace_snapshot_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
            "commit_subject_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.base_sha, name="base_sha")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitPlanError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitPlanError("repository is invalid")
        if (
            not isinstance(self.executed_command_id, str)
            or _COMMAND_ID.fullmatch(self.executed_command_id) is None
        ):
            raise PilotExactTaskLocalCommitPlanError(
                "executed_command_id is invalid"
            )
        if type(self.post_execution_workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskLocalCommitPlanError(
                "post-execution workspace snapshot is invalid"
            )
        try:
            replayed_snapshot = GitWorkspaceSnapshot.from_mapping(
                self.post_execution_workspace_snapshot.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskLocalCommitPlanError(
                "post-execution workspace snapshot replay failed"
            ) from exc
        if (
            replayed_snapshot != self.post_execution_workspace_snapshot
            or replayed_snapshot.sha256
            != self.post_execution_workspace_snapshot_sha256
            or replayed_snapshot.head_sha != self.base_sha
            or replayed_snapshot.staged_patch_sha256 != self.candidate_patch_sha256
            or replayed_snapshot.staged_patch_bytes != self.candidate_patch_bytes
            or replayed_snapshot.staged_patch_bytes <= 0
            or replayed_snapshot.unstaged_patch_bytes != 0
            or replayed_snapshot.untracked_path_count != 0
        ):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan candidate/workspace identity is inconsistent"
            )
        for name, value, upper in (
            ("candidate_patch_bytes", self.candidate_patch_bytes, 32 * 1024 * 1024),
            ("changed_file_count", self.changed_file_count, 200),
            ("added_lines", self.added_lines, 50_000),
            ("deleted_lines", self.deleted_lines, 50_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > upper
            ):
                raise PilotExactTaskLocalCommitPlanError(f"{name} is invalid")
        if self.candidate_patch_bytes <= 0:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan requires a non-empty candidate patch"
            )
        if (
            not isinstance(self.changed_paths, tuple)
            or not self.changed_paths
            or len(self.changed_paths) != self.changed_file_count
            or len(set(self.changed_paths)) != len(self.changed_paths)
        ):
            raise PilotExactTaskLocalCommitPlanError("changed_paths is invalid")
        for index, path in enumerate(self.changed_paths):
            if normalize_repo_path(path, name=f"changed_paths[{index}]") != path:
                raise PilotExactTaskLocalCommitPlanError(
                    "changed_paths are not canonical"
                )
        if (
            not isinstance(self.required_tests, tuple)
            or not self.required_tests
            or len(set(self.required_tests)) != len(self.required_tests)
            or any(
                not isinstance(item, str)
                or _COMMAND_ID.fullmatch(item) is None
                for item in self.required_tests
            )
            or self.required_tests != (self.executed_command_id,)
        ):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan requires exact one-command test coverage"
            )
        if self.commit_operation != PILOT_EXACT_TASK_LOCAL_COMMIT_OPERATION:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit operation is unsupported"
            )
        if self.commit_message_policy != PILOT_EXACT_TASK_LOCAL_COMMIT_MESSAGE_POLICY:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit message policy is unsupported"
            )
        expected_subject = _commit_subject(self.task_id)
        if (
            self.commit_subject != expected_subject
            or hashlib.sha256(self.commit_subject.encode("utf-8")).hexdigest()
            != self.commit_subject_sha256
        ):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit subject is not deterministic"
            )
        evaluated_time = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        planned_time = _utc(self.planned_at_utc, name="planned_at_utc")
        if planned_time < evaluated_time:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan timestamp precedes source evaluation"
            )

        required_true = (
            "post_execution_evaluation_authenticated",
            "mechanical_evaluation_passed",
            "fresh_workspace_snapshot_matched",
            "candidate_patch_bound",
            "commit_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan evidence is incomplete"
            )
        forced_false = (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan cannot grant write/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan authority is unsupported"
            )

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_local_commit_plan_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            if name == "post_execution_workspace_snapshot":
                result[name] = value.to_dict()
            elif name in {"changed_paths", "required_tests"}:
                result[name] = list(value)
            else:
                result[name] = value
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitPlan":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan fields mismatch"
            )
        data = dict(value)
        try:
            data["post_execution_workspace_snapshot"] = (
                GitWorkspaceSnapshot.from_mapping(
                    data["post_execution_workspace_snapshot"]
                )
            )
            data["changed_paths"] = tuple(data["changed_paths"])
            data["required_tests"] = tuple(data["required_tests"])
        except Exception as exc:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan nested evidence is invalid"
            ) from exc
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskLocalCommitPlan":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitPlanError(
                "local commit plan JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_local_commit_plan(
    *,
    evaluation_receipt: PilotExactTaskPostExecutionEvaluationReceipt,
    now_provider,
) -> PilotExactTaskLocalCommitPlan:
    evaluation, inputs = _require_live_post_execution_evaluation(evaluation_receipt)
    task = inputs["task"]

    first = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_evaluation(evaluation, first)

    subject = _commit_subject(task.task_id)
    planned_at = now_provider()
    evaluated_time = _utc(evaluation.evaluated_at_utc, name="evaluated_at_utc")
    planned_time = _utc(planned_at, name="planned_at_utc")
    if planned_time < evaluated_time:
        raise PilotExactTaskLocalCommitPlanError(
            "system clock moved backwards after post-execution evaluation"
        )
    plan = PilotExactTaskLocalCommitPlan(
        post_execution_evaluation_sha256=evaluation.sha256,
        execution_transaction_sha256=evaluation.execution_transaction_sha256,
        tier_a_receipt_sha256=evaluation.tier_a_receipt_sha256,
        execution_nonce_sha256=evaluation.execution_nonce_sha256,
        development_task_sha256=evaluation.development_task_sha256,
        task_id=task.task_id,
        repository=task.repository,
        base_sha=task.base_sha,
        fixed_command_plan_sha256=evaluation.fixed_command_plan_sha256,
        post_execution_workspace_snapshot=evaluation.post_execution_workspace_snapshot,
        post_execution_workspace_snapshot_sha256=(
            evaluation.post_execution_workspace_snapshot_sha256
        ),
        candidate_patch_sha256=evaluation.candidate_patch_sha256,
        candidate_patch_bytes=evaluation.candidate_patch_bytes,
        candidate_numstat_sha256=evaluation.candidate_numstat_sha256,
        changed_paths=evaluation.changed_paths,
        changed_file_count=evaluation.changed_file_count,
        added_lines=evaluation.added_lines,
        deleted_lines=evaluation.deleted_lines,
        scope_policy_sha256=evaluation.scope_policy_sha256,
        executed_command_id=evaluation.executed_command_id,
        required_tests=evaluation.required_tests,
        commit_operation=PILOT_EXACT_TASK_LOCAL_COMMIT_OPERATION,
        commit_message_policy=PILOT_EXACT_TASK_LOCAL_COMMIT_MESSAGE_POLICY,
        commit_subject=subject,
        commit_subject_sha256=hashlib.sha256(subject.encode("utf-8")).hexdigest(),
        evaluated_at_utc=evaluation.evaluated_at_utc,
        planned_at_utc=planned_at,
    )

    second = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_evaluation(evaluation, second)
    if second != first or second.sha256 != first.sha256:
        raise PilotExactTaskLocalCommitPlanError(
            "workspace changed while local commit plan was materialized"
        )

    _mark_local_commit_plan_authenticated(plan, evaluation)
    if plan.plan_authenticated is not True:
        raise PilotExactTaskLocalCommitPlanError(
            "local commit plan lost live provenance"
        )
    return plan


def materialize_pilot_exact_task_local_commit_plan(
    evaluation_receipt: PilotExactTaskPostExecutionEvaluationReceipt,
) -> PilotExactTaskLocalCommitPlan:
    """Host-pinned ADR-DC-041 inert local-commit-plan entrypoint."""
    try:
        return _materialize_verified_pilot_exact_task_local_commit_plan(
            evaluation_receipt=evaluation_receipt,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitPlanError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitPlanError(
            "host-controlled local commit planning failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_SCOPE",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OPERATION",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_MESSAGE_POLICY",
    "PilotExactTaskLocalCommitPlanError",
    "PilotExactTaskLocalCommitPlan",
    "materialize_pilot_exact_task_local_commit_plan",
]
