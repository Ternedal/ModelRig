"""Inert ADR-DC-029 requirements for one later exact task-execution admission.

This layer accepts only one fully satisfied ADR-DC-028 host-attestation proof and
freezes the additional authority/evidence a later one-shot task-execution
admission must establish.  It does not authorize or execute a task.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ._improvement_pilot_execution_admission_attestation_impl import (
    PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY,
    PilotExecutionAdmissionAttestationProof,
)

PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-admission-requirements/v1"
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-task-execution-admission-requirements-only"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class PilotExactTaskExecutionAdmissionRequirementsError(ValueError):
    """Exact-task execution-admission requirements are malformed or unsafe."""


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
        raise PilotExactTaskExecutionAdmissionRequirementsError(
            "exact-task execution-admission requirements are not canonical JSON"
        ) from exc


def _hex(value: Any, *, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskExecutionAdmissionRequirementsError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionAdmissionRequirementsError(f"{name} is invalid")
    return value


def _require_satisfied_attestation(
    value: Any,
) -> PilotExecutionAdmissionAttestationProof:
    if type(value) is not PilotExecutionAdmissionAttestationProof:
        raise PilotExactTaskExecutionAdmissionRequirementsError(
            "exact ADR-DC-028 PilotExecutionAdmissionAttestationProof is required"
        )
    try:
        replayed = PilotExecutionAdmissionAttestationProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutionAdmissionRequirementsError(
            "ADR-DC-028 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionAdmissionRequirementsError(
            "ADR-DC-028 proof replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY
        or value.host_attestation_verified is not True
        or value.execution_admission_observed is not True
        or value.execution_admission_satisfied is not True
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
        raise PilotExactTaskExecutionAdmissionRequirementsError(
            "exact-task admission requires a satisfied inert ADR-DC-028 proof"
        )
    return value


def _proof_binding(proof: PilotExecutionAdmissionAttestationProof) -> dict[str, Any]:
    exact = _require_satisfied_attestation(proof)
    requirements = exact.attestation.packet.admission_requirements
    return {
        "admission_attestation_proof_sha256": exact.sha256,
        "admission_attestation_sha256": exact.attestation_sha256,
        "admission_attestation_signature_sha256": exact.signature_sha256,
        "admission_packet_sha256": exact.packet_sha256,
        "start_receipt_sha256": exact.start_receipt_sha256,
        "repository": requirements.repository,
        "base_sha": requirements.base_sha,
        "requested_main_sha": requirements.requested_main_sha,
        "trial_id": requirements.trial_id,
        "operator_surface": requirements.operator_surface,
        "selected_pilot_task_id": requirements.selected_pilot_task_id,
        "workspace_root_path_sha256": requirements.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": (
            requirements.local_commits_allowed_by_human_scope
        ),
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionAdmissionRequirements:
    admission_attestation_proof: PilotExecutionAdmissionAttestationProof
    admission_attestation_proof_sha256: str
    admission_attestation_sha256: str
    admission_attestation_signature_sha256: str
    admission_packet_sha256: str
    start_receipt_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    fresh_host_attestation_reverification_required: bool = True
    fresh_live_consumption_revalidation_required: bool = True
    fresh_human_task_execution_authorization_required: bool = True
    one_shot_execution_nonce_required: bool = True
    host_local_execution_admission_ledger_required: bool = True
    exact_allowlisted_task_registry_entry_required: bool = True
    exact_selected_task_required: bool = True
    canonical_workspace_revalidation_required: bool = True
    exact_source_base_head_binding_required: bool = True
    exact_toolchain_binding_required: bool = True
    feature_flag_enabled_reobservation_required: bool = True
    native_windows_isolation_revalidation_required: bool = True
    trusted_git_closure_revalidation_required: bool = True
    kill_switch_armed_revalidation_required: bool = True
    revoke_not_asserted_revalidation_required: bool = True
    restart_recovery_revalidation_required: bool = True
    network_write_blocked_revalidation_required: bool = True
    credentials_absent_revalidation_required: bool = True
    general_shell_forbidden: bool = True
    model_defined_commands_forbidden: bool = True
    unattended_cadence_forbidden: bool = True
    exact_fixed_command_plan_required: bool = True
    bounded_execution_budget_required: bool = True
    manual_operator_invocation_required: bool = True
    post_execution_receipt_required: bool = True
    task_execution_admission_observed: bool = False
    task_execution_authorized: bool = False
    task_execution_started: bool = False
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "exact-task execution-admission requirements schema unsupported"
            )
        proof = _require_satisfied_attestation(self.admission_attestation_proof)
        for name in (
            "admission_attestation_proof_sha256",
            "admission_attestation_sha256",
            "admission_attestation_signature_sha256",
            "admission_packet_sha256",
            "start_receipt_sha256",
            "workspace_root_path_sha256",
        ):
            _hex(getattr(self, name), pattern=_HEX64, name=name)
        for name in ("base_sha", "requested_main_sha"):
            _hex(getattr(self, name), pattern=_HEX40, name=name)
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "repository is unsupported"
            )
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        expected = _proof_binding(proof)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                f"exact-task admission proof binding mismatch: {mismatch}"
            )
        required_true = (
            "fresh_host_attestation_reverification_required",
            "fresh_live_consumption_revalidation_required",
            "fresh_human_task_execution_authorization_required",
            "one_shot_execution_nonce_required",
            "host_local_execution_admission_ledger_required",
            "exact_allowlisted_task_registry_entry_required",
            "exact_selected_task_required",
            "canonical_workspace_revalidation_required",
            "exact_source_base_head_binding_required",
            "exact_toolchain_binding_required",
            "feature_flag_enabled_reobservation_required",
            "native_windows_isolation_revalidation_required",
            "trusted_git_closure_revalidation_required",
            "kill_switch_armed_revalidation_required",
            "revoke_not_asserted_revalidation_required",
            "restart_recovery_revalidation_required",
            "network_write_blocked_revalidation_required",
            "credentials_absent_revalidation_required",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "unattended_cadence_forbidden",
            "exact_fixed_command_plan_required",
            "bounded_execution_budget_required",
            "manual_operator_invocation_required",
            "post_execution_receipt_required",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "all exact-task execution-admission requirements must stay enabled"
            )
        forced_false = (
            "task_execution_admission_observed",
            "task_execution_authorized",
            "task_execution_started",
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
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "requirements cannot grant task execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "requirements authority invalid"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskExecutionAdmissionRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "requirements fields mismatch"
            )
        data = dict(value)
        proof = data.get("admission_attestation_proof")
        if not isinstance(proof, Mapping):
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "admission_attestation_proof must be an object"
            )
        try:
            data["admission_attestation_proof"] = (
                PilotExecutionAdmissionAttestationProof.from_mapping(proof)
            )
        except Exception as exc:
            raise PilotExactTaskExecutionAdmissionRequirementsError(
                "nested ADR-DC-028 proof is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.admission_attestation_proof.to_dict()
                if name == "admission_attestation_proof"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_execution_admission_requirements(
    proof: PilotExecutionAdmissionAttestationProof,
) -> PilotExactTaskExecutionAdmissionRequirements:
    exact = _require_satisfied_attestation(proof)
    return PilotExactTaskExecutionAdmissionRequirements(
        admission_attestation_proof=exact,
        **_proof_binding(exact),
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY",
    "PilotExactTaskExecutionAdmissionRequirementsError",
    "PilotExactTaskExecutionAdmissionRequirements",
    "build_pilot_exact_task_execution_admission_requirements",
]
