"""Exact-bound, non-authorizing ADR-DC-031 task-execution revalidation packet.

This packet binds one complete set of evidence digests to one exact, verified
ADR-DC-030 human task-execution authorization proof. It performs no host I/O and
makes no claim that the referenced evidence is true. A later host-controlled
verification boundary must fresh-revalidate the evidence before any execution
admission can be issued.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .improvement_pilot_exact_task_execution_authorization import (
    PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskExecutionAuthorizationProof,
)

PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-revalidation-observation-packet/v1"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY = (
    "dc-l16-exact-task-execution-revalidation-observation-packet-only"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

EVIDENCE_FIELDS = (
    "fresh_host_attestation_reverification_evidence_sha256",
    "fresh_live_consumption_revalidation_evidence_sha256",
    "fresh_human_task_execution_authorization_evidence_sha256",
    "one_shot_execution_nonce_evidence_sha256",
    "host_local_execution_admission_ledger_evidence_sha256",
    "exact_allowlisted_task_registry_entry_evidence_sha256",
    "exact_selected_task_evidence_sha256",
    "canonical_workspace_revalidation_evidence_sha256",
    "exact_source_base_head_binding_evidence_sha256",
    "exact_toolchain_binding_evidence_sha256",
    "feature_flag_enabled_reobservation_evidence_sha256",
    "native_windows_isolation_revalidation_evidence_sha256",
    "trusted_git_closure_revalidation_evidence_sha256",
    "kill_switch_armed_revalidation_evidence_sha256",
    "revoke_not_asserted_revalidation_evidence_sha256",
    "restart_recovery_revalidation_evidence_sha256",
    "network_write_blocked_revalidation_evidence_sha256",
    "credentials_absent_revalidation_evidence_sha256",
    "general_shell_forbidden_evidence_sha256",
    "model_defined_commands_forbidden_evidence_sha256",
    "unattended_cadence_forbidden_evidence_sha256",
    "exact_fixed_command_plan_evidence_sha256",
    "bounded_execution_budget_evidence_sha256",
    "manual_operator_invocation_evidence_sha256",
    "post_execution_receipt_capability_evidence_sha256",
)

_FIELDS = {
    "schema",
    "execution_authorization_proof",
    "execution_authorization_proof_sha256",
    "execution_authorization_signature_sha256",
    "execution_requirements_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_signature_sha256",
    "start_receipt_sha256",
    "execution_nonce_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed_by_human_scope",
    "observation_id",
    "observer_actor_id",
    "observed_at_utc",
    *EVIDENCE_FIELDS,
    "observation_set_complete",
    "human_authorization_proof_bound",
    "evidence_verified",
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
    "authority",
}


class PilotExactTaskExecutionRevalidationObservationError(ValueError):
    """Exact-task revalidation evidence is malformed, rebound or over-authorizing."""


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
        raise PilotExactTaskExecutionRevalidationObservationError(
            "exact-task revalidation observation is not canonical JSON"
        ) from exc


def _hex(value: Any, *, name: str, pattern: re.Pattern[str] = _HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationObservationError(f"{name} is invalid")
    if pattern is _HEX64 and value == "0" * 64:
        raise PilotExactTaskExecutionRevalidationObservationError(
            f"{name} must not be a placeholder"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskExecutionRevalidationObservationError(
            f"{name} is invalid"
        ) from exc


def _require_authorization_proof(
    value: Any,
) -> PilotExactTaskExecutionAuthorizationProof:
    if type(value) is not PilotExactTaskExecutionAuthorizationProof:
        raise PilotExactTaskExecutionRevalidationObservationError(
            "exact ADR-DC-030 PilotExactTaskExecutionAuthorizationProof is required"
        )
    try:
        replayed = PilotExactTaskExecutionAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskExecutionRevalidationObservationError(
            "ADR-DC-030 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionRevalidationObservationError(
            "ADR-DC-030 proof replay identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_task_execution_authorization_verified is not True
        or value.one_shot_execution_required is not True
        or value.execution_authorization_consumed is not False
        or value.task_execution_admission_observed is not False
        or value.task_execution_authorized is not False
        or value.task_execution_started is not False
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
        raise PilotExactTaskExecutionRevalidationObservationError(
            "revalidation packet requires an inert verified ADR-DC-030 proof"
        )
    return value


def _proof_binding(
    proof: PilotExactTaskExecutionAuthorizationProof,
) -> dict[str, Any]:
    exact = _require_authorization_proof(proof)
    authorization = exact.authorization
    return {
        "execution_authorization_proof_sha256": exact.sha256,
        "execution_authorization_signature_sha256": exact.signature_sha256,
        "execution_requirements_sha256": exact.execution_requirements_sha256,
        "admission_attestation_proof_sha256": exact.admission_attestation_proof_sha256,
        "admission_attestation_signature_sha256": (
            exact.admission_attestation_signature_sha256
        ),
        "start_receipt_sha256": exact.start_receipt_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "repository": authorization.repository,
        "base_sha": authorization.base_sha,
        "requested_main_sha": authorization.requested_main_sha,
        "trial_id": authorization.trial_id,
        "operator_surface": authorization.operator_surface,
        "selected_pilot_task_id": authorization.selected_pilot_task_id,
        "workspace_root_path_sha256": authorization.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": (
            authorization.local_commits_allowed_by_human_scope
        ),
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionRevalidationObservationPacket:
    execution_authorization_proof: PilotExactTaskExecutionAuthorizationProof
    execution_authorization_proof_sha256: str
    execution_authorization_signature_sha256: str
    execution_requirements_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_signature_sha256: str
    start_receipt_sha256: str
    execution_nonce_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    observation_id: str
    observer_actor_id: str
    observed_at_utc: str
    fresh_host_attestation_reverification_evidence_sha256: str
    fresh_live_consumption_revalidation_evidence_sha256: str
    fresh_human_task_execution_authorization_evidence_sha256: str
    one_shot_execution_nonce_evidence_sha256: str
    host_local_execution_admission_ledger_evidence_sha256: str
    exact_allowlisted_task_registry_entry_evidence_sha256: str
    exact_selected_task_evidence_sha256: str
    canonical_workspace_revalidation_evidence_sha256: str
    exact_source_base_head_binding_evidence_sha256: str
    exact_toolchain_binding_evidence_sha256: str
    feature_flag_enabled_reobservation_evidence_sha256: str
    native_windows_isolation_revalidation_evidence_sha256: str
    trusted_git_closure_revalidation_evidence_sha256: str
    kill_switch_armed_revalidation_evidence_sha256: str
    revoke_not_asserted_revalidation_evidence_sha256: str
    restart_recovery_revalidation_evidence_sha256: str
    network_write_blocked_revalidation_evidence_sha256: str
    credentials_absent_revalidation_evidence_sha256: str
    general_shell_forbidden_evidence_sha256: str
    model_defined_commands_forbidden_evidence_sha256: str
    unattended_cadence_forbidden_evidence_sha256: str
    exact_fixed_command_plan_evidence_sha256: str
    bounded_execution_budget_evidence_sha256: str
    manual_operator_invocation_evidence_sha256: str
    post_execution_receipt_capability_evidence_sha256: str
    observation_set_complete: bool = True
    human_authorization_proof_bound: bool = True
    evidence_verified: bool = False
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_SCHEMA:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "exact-task revalidation observation schema is unsupported"
            )
        proof = _require_authorization_proof(self.execution_authorization_proof)
        expected = _proof_binding(proof)
        for name, item in expected.items():
            if getattr(self, name) != item:
                raise PilotExactTaskExecutionRevalidationObservationError(
                    f"exact-task revalidation proof binding mismatch: {name}"
                )
        for name in (
            "execution_authorization_proof_sha256",
            "execution_authorization_signature_sha256",
            "execution_requirements_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "start_receipt_sha256",
            "execution_nonce_sha256",
            "workspace_root_path_sha256",
        ):
            _hex(getattr(self, name), name=name)
        for name in ("base_sha", "requested_main_sha"):
            _hex(getattr(self, name), name=name, pattern=_HEX40)
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskExecutionRevalidationObservationError(
                "repository is unsupported"
            )
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        _identifier(self.observation_id, name="observation_id")
        _identifier(self.observer_actor_id, name="observer_actor_id")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        verified = _utc(proof.verified_at_utc, name="ADR-DC-030 verified_at_utc")
        expires = _utc(proof.authorization.expires_at_utc, name="ADR-DC-030 expires_at_utc")
        if observed < verified:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "revalidation observation predates ADR-DC-030 verification"
            )
        if observed > expires:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "revalidation observation falls outside ADR-DC-030 authorization window"
            )
        for name in EVIDENCE_FIELDS:
            _hex(getattr(self, name), name=name)
        if (
            self.fresh_human_task_execution_authorization_evidence_sha256
            != proof.sha256
        ):
            raise PilotExactTaskExecutionRevalidationObservationError(
                "human execution authorization evidence must bind the exact ADR-DC-030 proof"
            )
        if self.one_shot_execution_nonce_evidence_sha256 != proof.execution_nonce_sha256:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "one-shot execution nonce evidence must bind the signed execution nonce"
            )
        if (
            self.observation_set_complete is not True
            or self.human_authorization_proof_bound is not True
            or self.evidence_verified is not False
            or self.task_execution_admission_observed is not False
            or self.task_execution_authorized is not False
            or self.task_execution_started is not False
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
            or self.authority
            != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY
        ):
            raise PilotExactTaskExecutionRevalidationObservationError(
                "exact-task revalidation observation authority boundary is invalid"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskExecutionRevalidationObservationPacket":
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "exact-task revalidation observation fields mismatch"
            )
        data = dict(value)
        proof = data.get("execution_authorization_proof")
        if not isinstance(proof, Mapping):
            raise PilotExactTaskExecutionRevalidationObservationError(
                "execution_authorization_proof must be an object"
            )
        try:
            data["execution_authorization_proof"] = (
                PilotExactTaskExecutionAuthorizationProof.from_mapping(proof)
            )
        except Exception as exc:
            raise PilotExactTaskExecutionRevalidationObservationError(
                "nested ADR-DC-030 proof is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "execution_authorization_proof": self.execution_authorization_proof.to_dict(),
            "execution_authorization_proof_sha256": self.execution_authorization_proof_sha256,
            "execution_authorization_signature_sha256": self.execution_authorization_signature_sha256,
            "execution_requirements_sha256": self.execution_requirements_sha256,
            "admission_attestation_proof_sha256": self.admission_attestation_proof_sha256,
            "admission_attestation_signature_sha256": self.admission_attestation_signature_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "trial_id": self.trial_id,
            "operator_surface": self.operator_surface,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed_by_human_scope": self.local_commits_allowed_by_human_scope,
            "observation_id": self.observation_id,
            "observer_actor_id": self.observer_actor_id,
            "observed_at_utc": self.observed_at_utc,
            **{name: getattr(self, name) for name in EVIDENCE_FIELDS},
            "observation_set_complete": self.observation_set_complete,
            "human_authorization_proof_bound": self.human_authorization_proof_bound,
            "evidence_verified": self.evidence_verified,
            "task_execution_admission_observed": self.task_execution_admission_observed,
            "task_execution_authorized": self.task_execution_authorized,
            "task_execution_started": self.task_execution_started,
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


def build_pilot_exact_task_execution_revalidation_observation_packet(
    *,
    execution_authorization_proof: PilotExactTaskExecutionAuthorizationProof,
    observation_id: str,
    observer_actor_id: str,
    observed_at_utc: str,
    evidence_sha256: Mapping[str, str],
) -> PilotExactTaskExecutionRevalidationObservationPacket:
    """Bind all 25 evidence references without asserting their host truth."""
    proof = _require_authorization_proof(execution_authorization_proof)
    if not isinstance(evidence_sha256, Mapping) or set(evidence_sha256) != set(
        EVIDENCE_FIELDS
    ):
        raise PilotExactTaskExecutionRevalidationObservationError(
            "exact-task revalidation evidence digest set mismatch"
        )
    return PilotExactTaskExecutionRevalidationObservationPacket(
        execution_authorization_proof=proof,
        observation_id=observation_id,
        observer_actor_id=observer_actor_id,
        observed_at_utc=observed_at_utc,
        **_proof_binding(proof),
        **{name: evidence_sha256[name] for name in EVIDENCE_FIELDS},
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY",
    "EVIDENCE_FIELDS",
    "PilotExactTaskExecutionRevalidationObservationError",
    "PilotExactTaskExecutionRevalidationObservationPacket",
    "build_pilot_exact_task_execution_revalidation_observation_packet",
]
