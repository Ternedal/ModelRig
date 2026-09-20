"""ADR-DC-109 verify and close one product-pilot execution.

Consumes one live ADR-DC-108 execution receipt, revalidates the retained ADR-DC-105
Tier-A substrate, and captures one fresh read-only Trusted-Git snapshot.

The boundary never performs Git recovery itself. It verifies that the workspace
matches the exact post-execution state already recorded by the canonical Tier-A
command receipt: the unchanged post-state on normal completion, or the exact-base
reset snapshot when the Tier-A receipt performed recovery.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contract import DevelopmentTask
from .tier_a_command_receipt import GitWorkspaceSnapshot, TierACommandReceiptError, _GitWorkspaceEvidence
from . import improvement_pilot_exact_task_product_pilot_execution as execution_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-verification/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_AUTHORITY = (
    "verified-product-pilot-execution-closure-evidence-only"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PilotExactTaskProductPilotExecutionVerificationError(ValueError):
    """The completed product-pilot execution cannot be safely verified."""


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
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "product-pilot execution verification is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotExecutionVerificationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionVerificationError(
            f"{name} is invalid"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            f"{name} is invalid"
        )
    return value


def _task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _require_live_execution(value: Any):
    if (
        type(value)
        is not execution_boundary.PilotExactTaskProductPilotExecutionReceipt
        or value.execution_authenticated is not True
        or value.product_pilot_started is not True
        or value.execution_plan_authenticated_at_launch is not True
        or value.task_execution_consumed is not True
        or value.one_shot_execution_enforced is not True
        or value.exact_pre_execution_snapshot_verified is not True
        or value.tier_a_command_receipt_verified is not True
        or value.task_execution_started is not True
        or value.task_execution_completed is not True
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
        or value.next_boundary_execution_verification_required is not True
    ):
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "live completed ADR-DC-108 execution receipt is required"
        )
    live = execution_boundary._get_live_product_pilot_execution_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "ADR-DC-108 live verification substrate is unavailable"
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
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "ADR-DC-108 DevelopmentTask provenance is inconsistent"
        )
    return value, live, task


def _capture_verified_post_execution_snapshot(
    *,
    live: Mapping[str, Any],
    task: DevelopmentTask,
) -> tuple[GitWorkspaceSnapshot, str]:
    try:
        git_runner = live["git_runner"]
        runtime_before = git_runner.evidence()
        evidence = _GitWorkspaceEvidence(live["workspace_root"], task, git_runner)
        snapshot = evidence.snapshot()
        runtime_after = git_runner.evidence()
    except (KeyError, TierACommandReceiptError) as exc:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "fresh post-execution Trusted-Git snapshot failed"
        ) from exc
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "post-execution Git runtime could not be revalidated"
        ) from exc
    if runtime_after.sha256 != runtime_before.sha256:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "Trusted-Git runtime changed during execution verification"
        )
    if snapshot.head_sha != task.base_sha:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "post-execution workspace HEAD no longer matches the task base"
        )
    if snapshot.has_unstaged_or_untracked:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "post-execution workspace contains unstaged or untracked material"
        )
    return snapshot, runtime_before.sha256


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotExecutionVerificationReceipt:
    execution_receipt_sha256: str
    execution_plan_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    tier_a_command_receipt_sha256: str
    pre_execution_workspace_snapshot_sha256: str
    expected_post_execution_workspace_snapshot_sha256: str
    post_execution_workspace_snapshot_sha256: str
    post_execution_workspace_snapshot: GitWorkspaceSnapshot
    git_runtime_evidence_sha256: str
    execution_outcome_passed: bool
    recovery_required: bool
    recovery_verified: bool
    execution_receipt_authenticated: bool = True
    tier_a_execution_verified: bool = True
    post_execution_workspace_verified: bool = True
    product_pilot_execution_closed: bool = True
    first_product_pilot_task_closed: bool = True
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_stack_consolidation_required: bool = True
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_AUTHORITY
        ):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "product-pilot execution verification identity is unsupported"
            )
        for name in (
            "execution_receipt_sha256",
            "execution_plan_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "tier_a_command_receipt_sha256",
            "pre_execution_workspace_snapshot_sha256",
            "expected_post_execution_workspace_snapshot_sha256",
            "post_execution_workspace_snapshot_sha256",
            "git_runtime_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        if type(self.post_execution_workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "canonical post-execution Git snapshot is required"
            )
        if (
            self.post_execution_workspace_snapshot.sha256
            != self.post_execution_workspace_snapshot_sha256
            or self.post_execution_workspace_snapshot_sha256
            != self.expected_post_execution_workspace_snapshot_sha256
        ):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "post-execution workspace does not match the expected Tier-A state"
            )
        if (
            self.post_execution_workspace_snapshot.head_sha
            != self.development_task_base_sha
            or self.post_execution_workspace_snapshot.has_unstaged_or_untracked
        ):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "post-execution workspace is unsafe"
            )
        for name in (
            "execution_outcome_passed",
            "recovery_required",
            "recovery_verified",
            "execution_receipt_authenticated",
            "tier_a_execution_verified",
            "post_execution_workspace_verified",
            "product_pilot_execution_closed",
            "first_product_pilot_task_closed",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
            "next_boundary_stack_consolidation_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise PilotExactTaskProductPilotExecutionVerificationError(
                    f"{name} must be boolean"
                )
        required_true = (
            "execution_receipt_authenticated",
            "tier_a_execution_verified",
            "post_execution_workspace_verified",
            "product_pilot_execution_closed",
            "first_product_pilot_task_closed",
            "next_boundary_stack_consolidation_required",
        )
        forced_false = (
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
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "product-pilot execution verification lacks closure evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "product-pilot execution verification grants mutation authority"
            )
        if self.recovery_required is self.execution_outcome_passed:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "recovery requirement must be inverse of execution pass state"
            )
        if self.execution_outcome_passed and self.recovery_verified:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "passing execution must not claim recovery"
            )
        if self.recovery_required and not self.recovery_verified:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "failed execution cannot close before recovery state is verified"
            )
        if (
            self.execution_outcome_passed
            and self.expected_post_execution_workspace_snapshot_sha256
            != self.pre_execution_workspace_snapshot_sha256
        ):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "passing execution did not preserve the exact planned workspace"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.post_execution_workspace_snapshot.to_dict()
                if name == "post_execution_workspace_snapshot"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "product-pilot execution verification fields mismatch"
            )
        raw = dict(value)
        try:
            raw["post_execution_workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
                raw["post_execution_workspace_snapshot"]
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "post-execution workspace snapshot is invalid"
            ) from exc
        return cls(**raw)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def verify_pilot_exact_task_product_pilot_execution(
    execution_receipt: execution_boundary.PilotExactTaskProductPilotExecutionReceipt,
) -> PilotExactTaskProductPilotExecutionVerificationReceipt:
    """Verify the exact post-execution/recovery workspace and close the first task."""
    source, live, task = _require_live_execution(execution_receipt)
    command = source.tier_a_command_receipt
    expected = (
        command.workspace_reset
        if command.workspace_reset_performed
        else command.workspace_after
    )
    if expected is None:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "Tier-A recovery state is missing"
        )
    fresh, git_runtime_sha = _capture_verified_post_execution_snapshot(
        live=live,
        task=task,
    )
    if fresh.sha256 != expected.sha256:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "current workspace no longer matches the Tier-A post-execution evidence"
        )
    if git_runtime_sha != command.git_runtime.sha256:
        raise PilotExactTaskProductPilotExecutionVerificationError(
            "current Trusted-Git evidence no longer matches the execution receipt"
        )
    if source.task_execution_passed:
        if (
            source.recovery_required
            or command.workspace_reset_performed
            or not command.workspace_unchanged
            or fresh.sha256 != source.workspace_snapshot_sha256
        ):
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "passing product-pilot execution lacks exact workspace preservation"
            )
        recovery_verified = False
    else:
        if not source.recovery_required:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "failed product-pilot execution lacks recovery requirement"
            )
        if command.workspace_reset_performed:
            reset = command.workspace_reset
            if (
                reset is None
                or reset.staged_patch_bytes != 0
                or reset.unstaged_patch_bytes != 0
                or reset.untracked_path_count != 0
            ):
                raise PilotExactTaskProductPilotExecutionVerificationError(
                    "Tier-A reset evidence is not exact-base clean"
                )
        elif not command.workspace_unchanged:
            raise PilotExactTaskProductPilotExecutionVerificationError(
                "failed execution changed workspace without Tier-A reset evidence"
            )
        recovery_verified = True

    return PilotExactTaskProductPilotExecutionVerificationReceipt(
        execution_receipt_sha256=source.sha256,
        execution_plan_sha256=source.execution_plan_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_id=source.development_task_id,
        development_task_sha256=source.development_task_sha256,
        development_task_base_sha=source.development_task_base_sha,
        fixed_command_id=source.fixed_command_id,
        tier_a_command_receipt_sha256=source.tier_a_command_receipt_sha256,
        pre_execution_workspace_snapshot_sha256=source.workspace_snapshot_sha256,
        expected_post_execution_workspace_snapshot_sha256=expected.sha256,
        post_execution_workspace_snapshot_sha256=fresh.sha256,
        post_execution_workspace_snapshot=fresh,
        git_runtime_evidence_sha256=git_runtime_sha,
        execution_outcome_passed=source.task_execution_passed,
        recovery_required=source.recovery_required,
        recovery_verified=recovery_verified,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_VERIFICATION_AUTHORITY",
    "PilotExactTaskProductPilotExecutionVerificationError",
    "PilotExactTaskProductPilotExecutionVerificationReceipt",
    "verify_pilot_exact_task_product_pilot_execution",
]
