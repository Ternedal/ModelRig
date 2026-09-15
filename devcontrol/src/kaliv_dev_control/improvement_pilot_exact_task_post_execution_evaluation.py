"""ADR-DC-040 mechanical post-execution evaluation for one exact Tier-A task.

This boundary accepts only the exact live ADR-DC-039 execution transaction,
requires a successful Tier-A receipt, fresh-rechecks the exact post-execution
workspace, evaluates the frozen staged candidate against the immutable
DevelopmentTask scope/budgets, and issues read-only mechanical evaluation
evidence.

It never grants local commit, remote publication, merge, release, deploy, or
production-activation authority.
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

from .contract import DevelopmentTask
from .policy import PathPolicy
from . import improvement_pilot_exact_task_execution_transaction as transaction_boundary
from .improvement_pilot_exact_task_execution_transaction import (
    PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY,
    PilotExactTaskExecutionTransactionReceipt,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-execution-evaluation/v1"
)
PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-task-mechanical-result-only"
)
PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCOPE = (
    "mechanical-post-execution-only-v1"
)
_SCOPE_POLICY_SCHEMA = "kaliv-rsi-dc-l16-exact-task-candidate-scope-policy/v1"
_MAX_NUMSTAT_BYTES = 32 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class PilotExactTaskPostExecutionEvaluationError(ValueError):
    """The exact post-execution candidate cannot be mechanically accepted."""


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
        raise PilotExactTaskPostExecutionEvaluationError(
            "post-execution evaluation is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskPostExecutionEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostExecutionEvaluationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostExecutionEvaluationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostExecutionEvaluationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _development_task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _scope_policy_payload(task: DevelopmentTask) -> dict[str, Any]:
    return {
        "schema": _SCOPE_POLICY_SCHEMA,
        "development_task_sha256": _development_task_sha256(task),
        "risk": task.risk.value,
        "allowed_paths": list(task.allowed_paths),
        "protected_paths": list(task.protected_paths),
        "required_tests": list(task.required_tests),
        "budget": task.budget.to_dict(),
        "merge_authority": task.merge_authority.value,
    }


def _scope_policy_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(
        _canonical(_scope_policy_payload(task)).encode("utf-8")
    ).hexdigest()


def _require_live_execution_transaction(
    value: Any,
) -> tuple[PilotExactTaskExecutionTransactionReceipt, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskExecutionTransactionReceipt:
        raise PilotExactTaskPostExecutionEvaluationError(
            "exact ADR-DC-039 execution transaction receipt is required"
        )
    try:
        replayed = PilotExactTaskExecutionTransactionReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPostExecutionEvaluationError(
            "ADR-DC-039 execution transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPostExecutionEvaluationError(
            "ADR-DC-039 execution transaction identity mismatch"
        )
    tier_a = value.tier_a_receipt
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.execution_consumed is not True
        or value.task_execution_started is not True
        or value.task_execution_completed is not True
        or value.task_execution_passed is not True
        or value.tier_a_receipt_verified is not True
        or tier_a.passed is not True
        or tier_a.workspace_unchanged is not True
        or tier_a.workspace_reset_performed is not False
        or tier_a.workspace_reset is not None
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPostExecutionEvaluationError(
            "post-execution evaluation requires one live successful ADR-DC-039 transaction"
        )
    inputs = transaction_boundary._get_live_execution_transaction_inputs(value)
    if inputs is None:
        raise PilotExactTaskPostExecutionEvaluationError(
            "ADR-DC-039 live execution inputs are unavailable"
        )
    task = inputs.get("task")
    plan = inputs.get("execution_plan")
    reservation = inputs.get("prelaunch_reservation")
    if (
        type(task) is not DevelopmentTask
        or plan is None
        or reservation is None
        or _development_task_sha256(task) != value.development_task_sha256
        or getattr(plan, "sha256", None) != value.execution_plan_sha256
        or getattr(plan, "fixed_command_plan_sha256", None)
        != value.fixed_command_plan_sha256
        or getattr(plan, "workspace_snapshot_sha256", None)
        != value.workspace_snapshot_sha256
        or getattr(reservation, "sha256", None)
        != value.prelaunch_reservation_sha256
        or value.tier_a_receipt.task_id != task.task_id
        or value.tier_a_receipt.base_sha != task.base_sha
        or value.tier_a_receipt.command_id != getattr(plan, "fixed_command_id", None)
    ):
        raise PilotExactTaskPostExecutionEvaluationError(
            "ADR-DC-039 execution transaction is not bound to its exact live task"
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
        raise PilotExactTaskPostExecutionEvaluationError(
            "fresh post-execution Trusted-Git snapshot failed"
        ) from exc


def _parse_numstat(payload: bytes) -> tuple[tuple[str, ...], int, int]:
    if not isinstance(payload, bytes):
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate numstat evidence must be bytes"
        )
    if not payload:
        return (), 0, 0
    if len(payload) > _MAX_NUMSTAT_BYTES or not payload.endswith(b"\0"):
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate numstat evidence is malformed or oversized"
        )
    records = payload[:-1].split(b"\0")
    paths: list[str] = []
    added_total = 0
    deleted_total = 0
    for record in records:
        parts = record.split(b"\t", 2)
        if len(parts) != 3:
            raise PilotExactTaskPostExecutionEvaluationError(
                "candidate numstat record is malformed"
            )
        added_raw, deleted_raw, path_raw = parts
        if (
            not added_raw
            or not deleted_raw
            or len(added_raw) > 10
            or len(deleted_raw) > 10
            or not added_raw.isdigit()
            or not deleted_raw.isdigit()
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "binary or non-canonical candidate numstat is not evaluable"
            )
        try:
            path = path_raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise PilotExactTaskPostExecutionEvaluationError(
                "candidate path is not canonical UTF-8"
            ) from exc
        if (
            not path
            or path.strip() != path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "candidate path contains non-canonical text"
            )
        paths.append(path)
        added_total += int(added_raw)
        deleted_total += int(deleted_raw)
    return tuple(paths), added_total, deleted_total


def _candidate_numstat(
    inputs: Mapping[str, Any],
) -> tuple[bytes, tuple[str, ...], int, int]:
    try:
        payload = inputs["git_runner"].run(
            (
                "diff",
                "--cached",
                "--numstat",
                "-z",
                "--no-renames",
                "--",
            ),
            cwd=Path(inputs["workspace_root"]),
            maximum=_MAX_NUMSTAT_BYTES,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate numstat collection failed"
        ) from exc
    paths, added_lines, deleted_lines = _parse_numstat(payload)
    return payload, paths, added_lines, deleted_lines


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
        receipt: Any,
        execution_receipt: PilotExactTaskExecutionTransactionReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(execution_receipt),
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, execution_ref = entry
        execution_receipt = execution_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or execution_receipt is None
            or execution_receipt.transaction_authenticated is not True
            or receipt.sha256 != digest
            or receipt.execution_transaction_sha256 != execution_receipt.sha256
        ):
            return None
        inputs = transaction_boundary._get_live_execution_transaction_inputs(
            execution_receipt
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["execution_transaction"] = execution_receipt
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_execution_evaluation_authenticated,
    _get_live_post_execution_evaluation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostExecutionEvaluationReceipt:
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    base_sha: str
    fixed_command_plan_sha256: str
    pre_execution_workspace_snapshot_sha256: str
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
    evaluated_at_utc: str
    execution_transaction_authenticated: bool = True
    task_execution_completed: bool = True
    task_execution_passed: bool = True
    post_execution_workspace_matched: bool = True
    candidate_patch_bound: bool = True
    candidate_patch_present: bool = True
    scope_policy_passed: bool = True
    required_tests_satisfied: bool = True
    mechanical_evaluation_passed: bool = True
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
    evaluation_scope: str = PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCHEMA:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation schema is unsupported"
            )
        if self.evaluation_scope != PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCOPE:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation scope is unsupported"
            )
        for name in (
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "pre_execution_workspace_snapshot_sha256",
            "post_execution_workspace_snapshot_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.base_sha, name="base_sha")
        if (
            not isinstance(self.task_id, str)
            or _TASK_ID.fullmatch(self.task_id) is None
        ):
            raise PilotExactTaskPostExecutionEvaluationError("task_id is invalid")
        if (
            not isinstance(self.executed_command_id, str)
            or _COMMAND_ID.fullmatch(self.executed_command_id) is None
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "executed_command_id is invalid"
            )
        if type(self.post_execution_workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution workspace snapshot is invalid"
            )
        try:
            replayed_snapshot = GitWorkspaceSnapshot.from_mapping(
                self.post_execution_workspace_snapshot.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution workspace snapshot replay validation failed"
            ) from exc
        snapshot = self.post_execution_workspace_snapshot
        if (
            replayed_snapshot != snapshot
            or replayed_snapshot.sha256 != self.post_execution_workspace_snapshot_sha256
            or snapshot.head_sha != self.base_sha
            or snapshot.sha256 != self.pre_execution_workspace_snapshot_sha256
            or snapshot.staged_patch_sha256 != self.candidate_patch_sha256
            or snapshot.staged_patch_bytes != self.candidate_patch_bytes
            or snapshot.unstaged_patch_bytes != 0
            or snapshot.untracked_path_count != 0
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution workspace identity is inconsistent"
            )
        if (
            isinstance(self.candidate_patch_bytes, bool)
            or not isinstance(self.candidate_patch_bytes, int)
            or self.candidate_patch_bytes <= 0
            or self.candidate_patch_sha256 == _EMPTY_SHA256
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "mechanical evaluation requires one non-empty frozen candidate patch"
            )
        if (
            not isinstance(self.changed_paths, tuple)
            or not self.changed_paths
            or any(not isinstance(path, str) or not path for path in self.changed_paths)
            or len(set(self.changed_paths)) != len(self.changed_paths)
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "changed_paths are invalid"
            )
        if (
            isinstance(self.changed_file_count, bool)
            or not isinstance(self.changed_file_count, int)
            or self.changed_file_count != len(self.changed_paths)
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "changed_file_count does not match changed_paths"
            )
        for name in ("added_lines", "deleted_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PilotExactTaskPostExecutionEvaluationError(
                    f"{name} must be a non-negative integer"
                )
        if self.candidate_numstat_sha256 == _EMPTY_SHA256:
            raise PilotExactTaskPostExecutionEvaluationError(
                "candidate numstat evidence must be non-empty"
            )
        if (
            not isinstance(self.required_tests, tuple)
            or self.required_tests != (self.executed_command_id,)
        ):
            raise PilotExactTaskPostExecutionEvaluationError(
                "one-shot mechanical evaluation must cover the sole required test"
            )
        _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        required_true = (
            "execution_transaction_authenticated",
            "task_execution_completed",
            "task_execution_passed",
            "post_execution_workspace_matched",
            "candidate_patch_bound",
            "candidate_patch_present",
            "scope_policy_passed",
            "required_tests_satisfied",
            "mechanical_evaluation_passed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution mechanical evaluation is incomplete"
            )
        forced_false = (
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
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation cannot grant publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation authority is unsupported"
            )

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_post_execution_evaluation_inputs(self) is not None

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
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPostExecutionEvaluationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation receipt fields mismatch"
            )
        data = dict(value)
        try:
            data["post_execution_workspace_snapshot"] = (
                GitWorkspaceSnapshot.from_mapping(
                    data["post_execution_workspace_snapshot"]
                )
            )
        except Exception as exc:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution workspace snapshot is invalid"
            ) from exc
        for name in ("changed_paths", "required_tests"):
            item = data[name]
            if not isinstance(item, list) or any(
                not isinstance(entry, str) for entry in item
            ):
                raise PilotExactTaskPostExecutionEvaluationError(
                    f"{name} must be a string array"
                )
            data[name] = tuple(item)
        return cls(**data)

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskPostExecutionEvaluationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskPostExecutionEvaluationError(
                "post-execution evaluation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_execution(
    *,
    execution_receipt: PilotExactTaskExecutionTransactionReceipt,
    now_provider,
) -> PilotExactTaskPostExecutionEvaluationReceipt:
    transaction, inputs = _require_live_execution_transaction(execution_receipt)
    task = inputs["task"]
    if tuple(task.required_tests) != (transaction.tier_a_receipt.command_id,):
        raise PilotExactTaskPostExecutionEvaluationError(
            "one-shot execution does not satisfy the DevelopmentTask required tests"
        )

    expected_workspace = transaction.tier_a_receipt.workspace_after
    first = _fresh_workspace_snapshot(inputs)
    if (
        first != expected_workspace
        or first.sha256 != expected_workspace.sha256
        or first.sha256 != transaction.workspace_snapshot_sha256
        or first.head_sha != task.base_sha
        or first.unstaged_patch_bytes != 0
        or first.untracked_path_count != 0
        or first.staged_patch_bytes <= 0
    ):
        raise PilotExactTaskPostExecutionEvaluationError(
            "fresh post-execution workspace does not match the successful frozen candidate"
        )

    numstat_payload, changed_paths, added_lines, deleted_lines = _candidate_numstat(
        inputs
    )
    second = _fresh_workspace_snapshot(inputs)
    if second != first or second.sha256 != first.sha256:
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate workspace changed during mechanical evaluation"
        )
    if not changed_paths:
        raise PilotExactTaskPostExecutionEvaluationError(
            "non-empty staged candidate produced no changed paths"
        )

    try:
        decision = PathPolicy(task).evaluate(
            changed_paths,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
        )
    except Exception as exc:
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate scope policy evaluation failed"
        ) from exc
    if decision.passed is not True:
        raise PilotExactTaskPostExecutionEvaluationError(
            "candidate patch violates immutable DevelopmentTask scope or budgets"
        )

    evaluated_at = now_provider()
    _utc(evaluated_at, name="evaluated_at_utc")
    result = PilotExactTaskPostExecutionEvaluationReceipt(
        execution_transaction_sha256=transaction.sha256,
        tier_a_receipt_sha256=transaction.tier_a_receipt_sha256,
        execution_nonce_sha256=transaction.execution_nonce_sha256,
        development_task_sha256=transaction.development_task_sha256,
        task_id=task.task_id,
        base_sha=task.base_sha,
        fixed_command_plan_sha256=transaction.fixed_command_plan_sha256,
        pre_execution_workspace_snapshot_sha256=transaction.workspace_snapshot_sha256,
        post_execution_workspace_snapshot=second,
        post_execution_workspace_snapshot_sha256=second.sha256,
        candidate_patch_sha256=second.staged_patch_sha256,
        candidate_patch_bytes=second.staged_patch_bytes,
        candidate_numstat_sha256=hashlib.sha256(numstat_payload).hexdigest(),
        changed_paths=decision.normalized_paths,
        changed_file_count=len(decision.normalized_paths),
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        scope_policy_sha256=_scope_policy_sha256(task),
        executed_command_id=transaction.tier_a_receipt.command_id,
        required_tests=tuple(task.required_tests),
        evaluated_at_utc=evaluated_at,
    )
    _mark_post_execution_evaluation_authenticated(result, transaction)
    if result.evaluation_authenticated is not True:
        raise PilotExactTaskPostExecutionEvaluationError(
            "post-execution evaluation lost live provenance"
        )
    return result


def evaluate_pilot_exact_task_execution(
    execution_receipt: PilotExactTaskExecutionTransactionReceipt,
) -> PilotExactTaskPostExecutionEvaluationReceipt:
    """Host-pinned ADR-DC-040 read-only mechanical evaluation entrypoint."""
    try:
        return _evaluate_verified_pilot_exact_task_execution(
            execution_receipt=execution_receipt,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostExecutionEvaluationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostExecutionEvaluationError(
            "host-controlled post-execution evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_EXECUTION_EVALUATION_SCOPE",
    "PilotExactTaskPostExecutionEvaluationError",
    "PilotExactTaskPostExecutionEvaluationReceipt",
    "evaluate_pilot_exact_task_execution",
]
