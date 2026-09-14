"""Inert ADR-DC-026 requirements for a later DC-L16 execution admission.

This module only freezes requirements derived from one exact ADR-DC-025
consumption receipt. It performs no host observation, product integration,
command registration, task execution, commit, remote mutation or activation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ._improvement_pilot_start_consumption_impl import (
    PILOT_START_CONSUMPTION_AUTHORITY,
    PilotStartConsumptionReceipt,
)

PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-execution-admission-requirements/v1"
)
PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY = (
    "dc-l16-pilot-execution-admission-requirements-only"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class PilotExecutionAdmissionRequirementsError(ValueError):
    """Execution-admission requirements are malformed or over-authorizing."""


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
        raise PilotExecutionAdmissionRequirementsError(
            "execution-admission requirements are not canonical JSON"
        ) from exc


def _hex(value: Any, *, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExecutionAdmissionRequirementsError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExecutionAdmissionRequirementsError(f"{name} is invalid")
    return value


def _require_consumed_receipt(value: Any) -> PilotStartConsumptionReceipt:
    if type(value) is not PilotStartConsumptionReceipt:
        raise PilotExecutionAdmissionRequirementsError(
            "exact ADR-DC-025 PilotStartConsumptionReceipt is required"
        )
    try:
        replayed = PilotStartConsumptionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExecutionAdmissionRequirementsError(
            "ADR-DC-025 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExecutionAdmissionRequirementsError(
            "ADR-DC-025 receipt replay identity mismatch"
        )
    if (
        value.authority != PILOT_START_CONSUMPTION_AUTHORITY
        or value.host_replay_guard_committed is not True
        or value.one_shot_start_required is not True
        or value.start_consumed is not True
        or value.start_receipt_issued is not True
        or value.pilot_start_authorized is not True
        or value.task_execution_authorized is not False
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
        raise PilotExecutionAdmissionRequirementsError(
            "execution-admission requirements need an inert consumed ADR-DC-025 receipt"
        )
    return value


def _receipt_binding(receipt: PilotStartConsumptionReceipt) -> dict[str, Any]:
    consumed = _require_consumed_receipt(receipt)
    authorization = consumed.authorization_proof.authorization
    return {
        "start_receipt_sha256": consumed.sha256,
        "authorization_proof_sha256": consumed.authorization_proof_sha256,
        "fresh_authorization_proof_sha256": consumed.fresh_authorization_proof_sha256,
        "authorization_signature_sha256": consumed.authorization_signature_sha256,
        "preflight_signature_sha256": consumed.preflight_signature_sha256,
        "start_nonce_sha256": consumed.start_nonce_sha256,
        "ledger_root_path_sha256": consumed.ledger_root_path_sha256,
        "repository": authorization.repository,
        "base_sha": authorization.base_sha,
        "requested_main_sha": authorization.requested_main_sha,
        "trial_id": authorization.trial_id,
        "operator_surface": authorization.operator_surface,
        "selected_pilot_task_id": authorization.selected_pilot_task_id,
        "workspace_root_path_sha256": authorization.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": authorization.local_commits_allowed,
    }


@dataclass(frozen=True, slots=True)
class PilotExecutionAdmissionRequirements:
    start_receipt: PilotStartConsumptionReceipt
    start_receipt_sha256: str
    authorization_proof_sha256: str
    fresh_authorization_proof_sha256: str
    authorization_signature_sha256: str
    preflight_signature_sha256: str
    start_nonce_sha256: str
    ledger_root_path_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    host_ledger_revalidation_required: bool = True
    fresh_upstream_authority_reverification_required: bool = True
    live_consumption_receipt_required_at_admission: bool = True
    allowlisted_task_registry_required: bool = True
    exact_selected_task_required: bool = True
    canonical_workspace_revalidation_required: bool = True
    feature_flag_enabled_observation_required: bool = True
    native_windows_isolation_required: bool = True
    trusted_git_closure_required: bool = True
    kill_switch_armed_required: bool = True
    revoke_not_asserted_required: bool = True
    restart_recovery_proof_required: bool = True
    network_write_blocked_required: bool = True
    credentials_absent_required: bool = True
    unattended_cadence_forbidden: bool = True
    general_shell_forbidden: bool = True
    model_defined_commands_forbidden: bool = True
    exact_source_base_head_binding_required: bool = True
    exact_toolchain_binding_required: bool = True
    execution_receipt_required: bool = True
    manual_operator_invocation_required: bool = True
    execution_admission_observed: bool = False
    task_execution_authorized: bool = False
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
    authority: str = PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA:
            raise PilotExecutionAdmissionRequirementsError("requirements schema unsupported")
        receipt = _require_consumed_receipt(self.start_receipt)
        for name in (
            "start_receipt_sha256",
            "authorization_proof_sha256",
            "fresh_authorization_proof_sha256",
            "authorization_signature_sha256",
            "preflight_signature_sha256",
            "start_nonce_sha256",
            "ledger_root_path_sha256",
            "workspace_root_path_sha256",
        ):
            _hex(getattr(self, name), pattern=_HEX64, name=name)
        for name in ("base_sha", "requested_main_sha"):
            _hex(getattr(self, name), pattern=_HEX40, name=name)
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotExecutionAdmissionRequirementsError("repository is unsupported")
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExecutionAdmissionRequirementsError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        expected = _receipt_binding(receipt)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExecutionAdmissionRequirementsError(
                f"execution-admission receipt binding mismatch: {mismatch}"
            )
        required_true = (
            "host_ledger_revalidation_required",
            "fresh_upstream_authority_reverification_required",
            "live_consumption_receipt_required_at_admission",
            "allowlisted_task_registry_required",
            "exact_selected_task_required",
            "canonical_workspace_revalidation_required",
            "feature_flag_enabled_observation_required",
            "native_windows_isolation_required",
            "trusted_git_closure_required",
            "kill_switch_armed_required",
            "revoke_not_asserted_required",
            "restart_recovery_proof_required",
            "network_write_blocked_required",
            "credentials_absent_required",
            "unattended_cadence_forbidden",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "exact_source_base_head_binding_required",
            "exact_toolchain_binding_required",
            "execution_receipt_required",
            "manual_operator_invocation_required",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExecutionAdmissionRequirementsError(
                "all execution-admission requirements must stay enabled"
            )
        forced_false = (
            "execution_admission_observed",
            "task_execution_authorized",
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
            raise PilotExecutionAdmissionRequirementsError(
                "requirements manifest cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY:
            raise PilotExecutionAdmissionRequirementsError("requirements authority invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExecutionAdmissionRequirements":
        if not isinstance(value, Mapping):
            raise PilotExecutionAdmissionRequirementsError("requirements must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise PilotExecutionAdmissionRequirementsError("requirements fields mismatch")
        data = dict(value)
        nested = data.get("start_receipt")
        if not isinstance(nested, Mapping):
            raise PilotExecutionAdmissionRequirementsError("start_receipt must be an object")
        try:
            data["start_receipt"] = PilotStartConsumptionReceipt.from_mapping(nested)
        except Exception as exc:
            raise PilotExecutionAdmissionRequirementsError(
                "nested ADR-DC-025 receipt is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.start_receipt.to_dict()
                if name == "start_receipt"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_execution_admission_requirements(
    receipt: PilotStartConsumptionReceipt,
) -> PilotExecutionAdmissionRequirements:
    consumed = _require_consumed_receipt(receipt)
    return PilotExecutionAdmissionRequirements(
        start_receipt=consumed,
        **_receipt_binding(consumed),
    )


__all__ = [
    "PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY",
    "PilotExecutionAdmissionRequirementsError",
    "PilotExecutionAdmissionRequirements",
    "build_pilot_execution_admission_requirements",
]
