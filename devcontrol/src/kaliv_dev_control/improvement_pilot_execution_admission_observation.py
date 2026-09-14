"""Exact-bound, non-authorizing ADR-DC-027 execution-admission observation packet.

The packet binds one complete set of evidence digests to one exact ADR-DC-026
requirements manifest. It performs no host I/O and deliberately does not claim
that the referenced evidence is true. A later host-controlled verifier must
freshly revalidate ADR-DC-025/024/023 authority and the concrete evidence before
execution admission can be observed or task execution can be authorized.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .improvement_pilot_execution_admission_requirements import (
    PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY,
    PilotExecutionAdmissionRequirements,
)

PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-execution-admission-observation-packet/v1"
)
PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY = (
    "dc-l16-pilot-execution-admission-observation-packet-only"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

EVIDENCE_FIELDS = (
    "host_ledger_revalidation_evidence_sha256",
    "fresh_upstream_authority_reverification_evidence_sha256",
    "live_consumption_receipt_evidence_sha256",
    "allowlisted_task_registry_evidence_sha256",
    "exact_selected_task_evidence_sha256",
    "canonical_workspace_revalidation_evidence_sha256",
    "feature_flag_enabled_observation_evidence_sha256",
    "native_windows_isolation_evidence_sha256",
    "trusted_git_closure_evidence_sha256",
    "kill_switch_armed_evidence_sha256",
    "revoke_not_asserted_evidence_sha256",
    "restart_recovery_proof_evidence_sha256",
    "network_write_blocked_evidence_sha256",
    "credentials_absent_evidence_sha256",
    "unattended_cadence_forbidden_evidence_sha256",
    "general_shell_forbidden_evidence_sha256",
    "model_defined_commands_forbidden_evidence_sha256",
    "exact_source_base_head_binding_evidence_sha256",
    "exact_toolchain_binding_evidence_sha256",
    "execution_receipt_evidence_sha256",
    "manual_operator_invocation_evidence_sha256",
)

_FIELDS = {
    "schema",
    "admission_requirements",
    "admission_requirements_sha256",
    "start_receipt_sha256",
    "observation_id",
    "observer_actor_id",
    "observed_at_utc",
    *EVIDENCE_FIELDS,
    "observation_set_complete",
    "evidence_verified",
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
    "authority",
}


class PilotExecutionAdmissionObservationError(ValueError):
    """Execution-admission observation is malformed, rebound or over-authorizing."""


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
        raise PilotExecutionAdmissionObservationError(
            "execution-admission observation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExecutionAdmissionObservationError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExecutionAdmissionObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExecutionAdmissionObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExecutionAdmissionObservationError(f"{name} is invalid") from exc


def _require_requirements(value: Any) -> PilotExecutionAdmissionRequirements:
    if type(value) is not PilotExecutionAdmissionRequirements:
        raise PilotExecutionAdmissionObservationError(
            "exact ADR-DC-026 PilotExecutionAdmissionRequirements is required"
        )
    try:
        replayed = PilotExecutionAdmissionRequirements.from_mapping(value.to_dict())
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotExecutionAdmissionObservationError(
            "ADR-DC-026 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExecutionAdmissionObservationError(
            "ADR-DC-026 requirements replay identity mismatch"
        )
    required_true = (
        value.host_ledger_revalidation_required,
        value.fresh_upstream_authority_reverification_required,
        value.live_consumption_receipt_required_at_admission,
        value.allowlisted_task_registry_required,
        value.exact_selected_task_required,
        value.canonical_workspace_revalidation_required,
        value.feature_flag_enabled_observation_required,
        value.native_windows_isolation_required,
        value.trusted_git_closure_required,
        value.kill_switch_armed_required,
        value.revoke_not_asserted_required,
        value.restart_recovery_proof_required,
        value.network_write_blocked_required,
        value.credentials_absent_required,
        value.unattended_cadence_forbidden,
        value.general_shell_forbidden,
        value.model_defined_commands_forbidden,
        value.exact_source_base_head_binding_required,
        value.exact_toolchain_binding_required,
        value.execution_receipt_required,
        value.manual_operator_invocation_required,
    )
    if (
        value.authority != PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        or any(item is not True for item in required_true)
        or value.execution_admission_observed is not False
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
        raise PilotExecutionAdmissionObservationError(
            "ADR-DC-026 requirements authority boundary is invalid"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExecutionAdmissionObservationPacket:
    admission_requirements: PilotExecutionAdmissionRequirements
    admission_requirements_sha256: str
    start_receipt_sha256: str
    observation_id: str
    observer_actor_id: str
    observed_at_utc: str
    host_ledger_revalidation_evidence_sha256: str
    fresh_upstream_authority_reverification_evidence_sha256: str
    live_consumption_receipt_evidence_sha256: str
    allowlisted_task_registry_evidence_sha256: str
    exact_selected_task_evidence_sha256: str
    canonical_workspace_revalidation_evidence_sha256: str
    feature_flag_enabled_observation_evidence_sha256: str
    native_windows_isolation_evidence_sha256: str
    trusted_git_closure_evidence_sha256: str
    kill_switch_armed_evidence_sha256: str
    revoke_not_asserted_evidence_sha256: str
    restart_recovery_proof_evidence_sha256: str
    network_write_blocked_evidence_sha256: str
    credentials_absent_evidence_sha256: str
    unattended_cadence_forbidden_evidence_sha256: str
    general_shell_forbidden_evidence_sha256: str
    model_defined_commands_forbidden_evidence_sha256: str
    exact_source_base_head_binding_evidence_sha256: str
    exact_toolchain_binding_evidence_sha256: str
    execution_receipt_evidence_sha256: str
    manual_operator_invocation_evidence_sha256: str
    observation_set_complete: bool = True
    evidence_verified: bool = False
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
    authority: str = PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA:
            raise PilotExecutionAdmissionObservationError(
                "execution-admission observation schema is unsupported"
            )
        requirements = _require_requirements(self.admission_requirements)
        _hex64(self.admission_requirements_sha256, name="admission_requirements_sha256")
        _hex64(self.start_receipt_sha256, name="start_receipt_sha256")
        if self.admission_requirements_sha256 != requirements.sha256:
            raise PilotExecutionAdmissionObservationError(
                "execution-admission requirements hash mismatch"
            )
        if self.start_receipt_sha256 != requirements.start_receipt_sha256:
            raise PilotExecutionAdmissionObservationError(
                "execution-admission start receipt binding mismatch"
            )
        _identifier(self.observation_id, name="observation_id")
        _identifier(self.observer_actor_id, name="observer_actor_id")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        consumed = _utc(
            requirements.start_receipt.consumed_at_utc,
            name="start receipt consumed_at_utc",
        )
        if observed < consumed:
            raise PilotExecutionAdmissionObservationError(
                "execution-admission observation predates start consumption"
            )
        for name in EVIDENCE_FIELDS:
            _hex64(getattr(self, name), name=name)
        if (
            self.observation_set_complete is not True
            or self.evidence_verified is not False
            or self.execution_admission_observed is not False
            or self.task_execution_authorized is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY
        ):
            raise PilotExecutionAdmissionObservationError(
                "execution-admission observation authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExecutionAdmissionObservationPacket":
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise PilotExecutionAdmissionObservationError(
                "execution-admission observation fields mismatch"
            )
        data = dict(value)
        requirements = data.get("admission_requirements")
        if not isinstance(requirements, Mapping):
            raise PilotExecutionAdmissionObservationError(
                "admission_requirements must be an object"
            )
        data["admission_requirements"] = (
            PilotExecutionAdmissionRequirements.from_mapping(requirements)
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "admission_requirements": self.admission_requirements.to_dict(),
            "admission_requirements_sha256": self.admission_requirements_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "observation_id": self.observation_id,
            "observer_actor_id": self.observer_actor_id,
            "observed_at_utc": self.observed_at_utc,
            **{name: getattr(self, name) for name in EVIDENCE_FIELDS},
            "observation_set_complete": self.observation_set_complete,
            "evidence_verified": self.evidence_verified,
            "execution_admission_observed": self.execution_admission_observed,
            "task_execution_authorized": self.task_execution_authorized,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_execution_admission_observation_packet(
    *,
    admission_requirements: PilotExecutionAdmissionRequirements,
    observation_id: str,
    observer_actor_id: str,
    observed_at_utc: str,
    evidence_sha256: Mapping[str, str],
) -> PilotExecutionAdmissionObservationPacket:
    """Bind all 21 evidence references without asserting host truth."""
    requirements = _require_requirements(admission_requirements)
    if not isinstance(evidence_sha256, Mapping) or set(evidence_sha256) != set(
        EVIDENCE_FIELDS
    ):
        raise PilotExecutionAdmissionObservationError(
            "execution-admission evidence digest set mismatch"
        )
    return PilotExecutionAdmissionObservationPacket(
        admission_requirements=requirements,
        admission_requirements_sha256=requirements.sha256,
        start_receipt_sha256=requirements.start_receipt_sha256,
        observation_id=observation_id,
        observer_actor_id=observer_actor_id,
        observed_at_utc=observed_at_utc,
        **{name: evidence_sha256[name] for name in EVIDENCE_FIELDS},
    )


__all__ = [
    "PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY",
    "EVIDENCE_FIELDS",
    "PilotExecutionAdmissionObservationError",
    "PilotExecutionAdmissionObservationPacket",
    "build_pilot_execution_admission_observation_packet",
]
