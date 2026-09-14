"""Inert ADR-DC-034 requirements for one exact Tier-A execution plan.

This layer can only be created from the exact live ADR-DC-033 admission receipt
returned by the successful host-local transaction.  It freezes what a later,
separate executor boundary must materialize and revalidate before it may consume
that admission.  It does not resolve a task registry, construct a Tier-A plan,
or execute anything.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_pilot_exact_task_execution_admission import (
    PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY,
    PilotExactTaskExecutionAdmissionReceipt,
)

PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-plan-requirements/v1"
)
PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-task-execution-plan-requirements-only"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class PilotExactTaskExecutionPlanRequirementsError(ValueError):
    """ADR-DC-034 execution-plan requirements are malformed or unsafe."""


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
        raise PilotExactTaskExecutionPlanRequirementsError(
            "exact-task execution-plan requirements are not canonical JSON"
        ) from exc


def _hex(value: Any, *, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskExecutionPlanRequirementsError(f"{name} is invalid")
    if pattern is _HEX64 and value == "0" * 64:
        raise PilotExactTaskExecutionPlanRequirementsError(
            f"{name} must not be a placeholder"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionPlanRequirementsError(f"{name} is invalid")
    return value


def _require_receipt(
    value: Any,
    *,
    require_live: bool,
) -> PilotExactTaskExecutionAdmissionReceipt:
    if type(value) is not PilotExactTaskExecutionAdmissionReceipt:
        raise PilotExactTaskExecutionPlanRequirementsError(
            "exact ADR-DC-033 PilotExactTaskExecutionAdmissionReceipt is required"
        )
    try:
        replayed = PilotExactTaskExecutionAdmissionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutionPlanRequirementsError(
            "ADR-DC-033 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionPlanRequirementsError(
            "ADR-DC-033 receipt replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        or value.host_replay_guard_committed is not True
        or value.execution_authorization_consumed is not True
        or value.one_shot_execution_required is not True
        or value.task_execution_admission_observed is not True
        or value.task_execution_authorized is not True
        or value.task_execution_started is not False
        or value.execution_consumed is not False
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
        raise PilotExactTaskExecutionPlanRequirementsError(
            "execution-plan requirements need one unconsumed inert ADR-DC-033 admission"
        )
    if require_live and value.transaction_authenticated is not True:
        raise PilotExactTaskExecutionPlanRequirementsError(
            "execution-plan requirements can only be issued from the live ADR-DC-033 receipt"
        )
    return value


def _receipt_binding(
    receipt: PilotExactTaskExecutionAdmissionReceipt,
) -> dict[str, Any]:
    exact = _require_receipt(receipt, require_live=False)
    packet = exact.revalidation_attestation_proof.attestation.packet
    return {
        "admission_receipt_sha256": exact.sha256,
        "admission_key_sha256": exact.admission_key_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "revalidation_attestation_proof_sha256": (
            exact.revalidation_attestation_proof_sha256
        ),
        "execution_authorization_proof_sha256": (
            exact.execution_authorization_proof_sha256
        ),
        "start_receipt_sha256": exact.start_receipt_sha256,
        "repository": packet.repository,
        "base_sha": packet.base_sha,
        "requested_main_sha": packet.requested_main_sha,
        "trial_id": packet.trial_id,
        "operator_surface": packet.operator_surface,
        "selected_pilot_task_id": exact.selected_pilot_task_id,
        "workspace_root_path_sha256": exact.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": (
            exact.local_commits_allowed_by_human_scope
        ),
    }


_REQUIRED_TRUE = (
    "live_admission_receipt_required",
    "exact_admission_receipt_identity_required",
    "one_shot_executor_consumption_required",
    "host_pinned_task_registry_required",
    "exact_development_task_required",
    "selected_pilot_task_mapping_required",
    "task_repository_base_match_required",
    "canonical_workspace_match_required",
    "single_fixed_command_required",
    "reviewed_nonempty_command_catalog_required",
    "exact_toolchain_binding_required",
    "signed_runtime_closure_required",
    "host_pinned_physical_verifier_required",
    "host_pinned_runtime_closure_verifier_required",
    "canonical_trusted_runtime_root_required",
    "host_pinned_trusted_git_runner_required",
    "control_plane_toolhost_binding_required",
    "reviewed_source_environment_required",
    "exact_native_process_limits_required",
    "caller_selected_executable_verifier_forbidden",
    "trusted_git_runtime_required",
    "native_windows_tier_a_required",
    "network_deny_required",
    "credentials_absent_required",
    "general_shell_forbidden",
    "model_defined_commands_forbidden",
    "unattended_cadence_forbidden",
    "exact_execution_budget_required",
    "manual_operator_invocation_required",
    "pre_execution_git_snapshot_required",
    "post_execution_tier_a_receipt_required",
    "workspace_drift_fail_closed_reset_required",
    "post_execution_consumption_receipt_required",
)

_FORCED_FALSE = (
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


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionPlanRequirements:
    admission_receipt: PilotExactTaskExecutionAdmissionReceipt
    admission_receipt_sha256: str
    admission_key_sha256: str
    execution_nonce_sha256: str
    revalidation_attestation_proof_sha256: str
    execution_authorization_proof_sha256: str
    start_receipt_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    live_admission_receipt_required: bool = True
    exact_admission_receipt_identity_required: bool = True
    one_shot_executor_consumption_required: bool = True
    host_pinned_task_registry_required: bool = True
    exact_development_task_required: bool = True
    selected_pilot_task_mapping_required: bool = True
    task_repository_base_match_required: bool = True
    canonical_workspace_match_required: bool = True
    single_fixed_command_required: bool = True
    reviewed_nonempty_command_catalog_required: bool = True
    exact_toolchain_binding_required: bool = True
    signed_runtime_closure_required: bool = True
    host_pinned_physical_verifier_required: bool = True
    host_pinned_runtime_closure_verifier_required: bool = True
    canonical_trusted_runtime_root_required: bool = True
    host_pinned_trusted_git_runner_required: bool = True
    control_plane_toolhost_binding_required: bool = True
    reviewed_source_environment_required: bool = True
    exact_native_process_limits_required: bool = True
    caller_selected_executable_verifier_forbidden: bool = True
    trusted_git_runtime_required: bool = True
    native_windows_tier_a_required: bool = True
    network_deny_required: bool = True
    credentials_absent_required: bool = True
    general_shell_forbidden: bool = True
    model_defined_commands_forbidden: bool = True
    unattended_cadence_forbidden: bool = True
    exact_execution_budget_required: bool = True
    manual_operator_invocation_required: bool = True
    pre_execution_git_snapshot_required: bool = True
    post_execution_tier_a_receipt_required: bool = True
    workspace_drift_fail_closed_reset_required: bool = True
    post_execution_consumption_receipt_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskExecutionPlanRequirementsError(
                "execution-plan requirements schema unsupported"
            )
        receipt = _require_receipt(self.admission_receipt, require_live=False)
        for name in (
            "admission_receipt_sha256",
            "admission_key_sha256",
            "execution_nonce_sha256",
            "revalidation_attestation_proof_sha256",
            "execution_authorization_proof_sha256",
            "start_receipt_sha256",
            "workspace_root_path_sha256",
        ):
            _hex(getattr(self, name), pattern=_HEX64, name=name)
        for name in ("base_sha", "requested_main_sha"):
            _hex(getattr(self, name), pattern=_HEX40, name=name)
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskExecutionPlanRequirementsError(
                "repository is unsupported"
            )
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskExecutionPlanRequirementsError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        expected = _receipt_binding(receipt)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionPlanRequirementsError(
                f"execution-plan receipt binding mismatch: {mismatch}"
            )
        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskExecutionPlanRequirementsError(
                "all exact execution-plan requirements must stay enabled"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskExecutionPlanRequirementsError(
                "execution-plan requirements cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY:
            raise PilotExactTaskExecutionPlanRequirementsError(
                "execution-plan requirements authority invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutionPlanRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskExecutionPlanRequirementsError(
                "execution-plan requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise PilotExactTaskExecutionPlanRequirementsError(
                "execution-plan requirements fields mismatch"
            )
        data = dict(value)
        receipt = data.get("admission_receipt")
        if not isinstance(receipt, Mapping):
            raise PilotExactTaskExecutionPlanRequirementsError(
                "admission_receipt must be an object"
            )
        try:
            data["admission_receipt"] = (
                PilotExactTaskExecutionAdmissionReceipt.from_mapping(receipt)
            )
        except Exception as exc:
            raise PilotExactTaskExecutionPlanRequirementsError(
                "nested ADR-DC-033 receipt is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.admission_receipt.to_dict()
                if name == "admission_receipt"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_execution_plan_requirements(
    receipt: PilotExactTaskExecutionAdmissionReceipt,
) -> PilotExactTaskExecutionPlanRequirements:
    exact = _require_receipt(receipt, require_live=True)
    return PilotExactTaskExecutionPlanRequirements(
        admission_receipt=exact,
        **_receipt_binding(exact),
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY",
    "PilotExactTaskExecutionPlanRequirementsError",
    "PilotExactTaskExecutionPlanRequirements",
    "build_pilot_exact_task_execution_plan_requirements",
]
