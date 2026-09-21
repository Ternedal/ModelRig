"""Host-attested verification model for one exact ADR-DC-027 evidence packet.

ADR-DC-028 signs the complete ADR-DC-027 packet plus one boolean result for each
of its 21 admission requirements. A verified signature can establish only that
those host-attested checks were recorded for the exact packet. It does not grant
task execution, local commit, remote mutation, merge, release, deploy or
production activation authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_execution_admission_observation import (
    PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY,
    PilotExecutionAdmissionObservationPacket,
)

PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-execution-admission-attestation/v1"
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-execution-admission-attestation-proof/v1"
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY = (
    "dc-l16-pilot-execution-admission-attestation-claim-only"
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY = (
    "verified-dc-l16-pilot-execution-admission-attestation-only"
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-pilot-execution-admission-attestor-v1"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

RESULT_FIELDS = (
    "host_ledger_revalidated",
    "fresh_upstream_authority_reverified",
    "live_consumption_receipt_verified",
    "allowlisted_task_registry_verified",
    "exact_selected_task_verified",
    "canonical_workspace_revalidated",
    "feature_flag_enabled_observed",
    "native_windows_isolation_verified",
    "trusted_git_closure_verified",
    "kill_switch_armed",
    "revoke_not_asserted",
    "restart_recovery_verified",
    "network_write_blocked",
    "credentials_absent",
    "unattended_cadence_forbidden_verified",
    "general_shell_forbidden_verified",
    "model_defined_commands_forbidden_verified",
    "exact_source_base_head_binding_verified",
    "exact_toolchain_binding_verified",
    "execution_receipt_requirement_verified",
    "manual_operator_invocation_verified",
)

_ATTESTATION_FIELDS = {
    "schema",
    "packet",
    "packet_sha256",
    "start_receipt_sha256",
    "attestation_id",
    "observer_host_id",
    "attested_at_utc",
    *RESULT_FIELDS,
    "host_attestation_verified",
    "execution_admission_observed",
    "execution_admission_satisfied",
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

_PROOF_FIELDS = {
    "schema",
    "attestation_sha256",
    "signature_sha256",
    "key_id",
    "issuer_actor_id",
    "issuer_system_id",
    "attestation",
    "verified_at_utc",
    "packet_sha256",
    "start_receipt_sha256",
    "host_attestation_verified",
    "execution_admission_observed",
    "execution_admission_satisfied",
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


class PilotExecutionAdmissionAttestationError(ValueError):
    """Execution-admission attestation is malformed, untrusted or unsafe."""


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
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission attestation is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExecutionAdmissionAttestationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExecutionAdmissionAttestationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExecutionAdmissionAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExecutionAdmissionAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExecutionAdmissionAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExecutionAdmissionAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_packet(value: Any) -> PilotExecutionAdmissionObservationPacket:
    if type(value) is not PilotExecutionAdmissionObservationPacket:
        raise PilotExecutionAdmissionAttestationError(
            "exact ADR-DC-027 PilotExecutionAdmissionObservationPacket is required"
        )
    try:
        replayed = PilotExecutionAdmissionObservationPacket.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExecutionAdmissionAttestationError(
            "ADR-DC-027 packet replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExecutionAdmissionAttestationError(
            "ADR-DC-027 packet replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY
        or value.observation_set_complete is not True
        or value.evidence_verified is not False
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
        raise PilotExecutionAdmissionAttestationError(
            "ADR-DC-027 packet is not inert exact evidence"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExecutionAdmissionAttestation:
    packet: PilotExecutionAdmissionObservationPacket
    packet_sha256: str
    start_receipt_sha256: str
    attestation_id: str
    observer_host_id: str
    attested_at_utc: str
    host_ledger_revalidated: bool
    fresh_upstream_authority_reverified: bool
    live_consumption_receipt_verified: bool
    allowlisted_task_registry_verified: bool
    exact_selected_task_verified: bool
    canonical_workspace_revalidated: bool
    feature_flag_enabled_observed: bool
    native_windows_isolation_verified: bool
    trusted_git_closure_verified: bool
    kill_switch_armed: bool
    revoke_not_asserted: bool
    restart_recovery_verified: bool
    network_write_blocked: bool
    credentials_absent: bool
    unattended_cadence_forbidden_verified: bool
    general_shell_forbidden_verified: bool
    model_defined_commands_forbidden_verified: bool
    exact_source_base_head_binding_verified: bool
    exact_toolchain_binding_verified: bool
    execution_receipt_requirement_verified: bool
    manual_operator_invocation_verified: bool
    host_attestation_verified: bool = False
    execution_admission_observed: bool = False
    execution_admission_satisfied: bool = False
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
    authority: str = PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation schema is unsupported"
            )
        packet = _require_packet(self.packet)
        _hex64(self.packet_sha256, name="packet_sha256")
        _hex64(self.start_receipt_sha256, name="start_receipt_sha256")
        if self.packet_sha256 != packet.sha256:
            raise PilotExecutionAdmissionAttestationError("packet hash mismatch")
        if self.start_receipt_sha256 != packet.start_receipt_sha256:
            raise PilotExecutionAdmissionAttestationError(
                "start receipt binding mismatch"
            )
        _identifier(self.attestation_id, name="attestation_id")
        _identifier(self.observer_host_id, name="observer_host_id")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        observed = _utc(packet.observed_at_utc, name="packet observed_at_utc")
        if attested < observed:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation predates observation packet"
            )
        for name in RESULT_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise PilotExecutionAdmissionAttestationError(
                    f"{name} must be boolean"
                )
        if (
            self.host_attestation_verified is not False
            or self.execution_admission_observed is not False
            or self.execution_admission_satisfied is not False
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
            or self.authority != PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY
        ):
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation authority boundary is invalid"
            )

    @property
    def all_checks_satisfied(self) -> bool:
        return all(getattr(self, name) is True for name in RESULT_FIELDS)

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExecutionAdmissionAttestation":
        data = dict(
            _strict(value, fields=_ATTESTATION_FIELDS, name="execution-admission attestation")
        )
        packet = data.get("packet")
        if not isinstance(packet, Mapping):
            raise PilotExecutionAdmissionAttestationError("packet is invalid")
        data["packet"] = PilotExecutionAdmissionObservationPacket.from_mapping(packet)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "packet": self.packet.to_dict(),
            "packet_sha256": self.packet_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "attestation_id": self.attestation_id,
            "observer_host_id": self.observer_host_id,
            "attested_at_utc": self.attested_at_utc,
            **{name: getattr(self, name) for name in RESULT_FIELDS},
            "host_attestation_verified": self.host_attestation_verified,
            "execution_admission_observed": self.execution_admission_observed,
            "execution_admission_satisfied": self.execution_admission_satisfied,
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


def build_pilot_execution_admission_attestation(
    *,
    packet: PilotExecutionAdmissionObservationPacket,
    attestation_id: str,
    observer_host_id: str,
    attested_at_utc: str,
    results: Mapping[str, bool],
) -> PilotExecutionAdmissionAttestation:
    exact_packet = _require_packet(packet)
    if not isinstance(results, Mapping) or set(results) != set(RESULT_FIELDS):
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission result set mismatch"
        )
    return PilotExecutionAdmissionAttestation(
        packet=exact_packet,
        packet_sha256=exact_packet.sha256,
        start_receipt_sha256=exact_packet.start_receipt_sha256,
        attestation_id=attestation_id,
        observer_host_id=observer_host_id,
        attested_at_utc=attested_at_utc,
        **{name: results[name] for name in RESULT_FIELDS},
    )


@dataclass(frozen=True, slots=True)
class PilotExecutionAdmissionAttestationProof:
    attestation_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    attestation: PilotExecutionAdmissionAttestation
    verified_at_utc: str
    packet_sha256: str
    start_receipt_sha256: str
    host_attestation_verified: bool = True
    execution_admission_observed: bool = True
    execution_admission_satisfied: bool = False
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
    authority: str = PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY
    schema: str = PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation proof schema is unsupported"
            )
        _hex64(self.attestation_sha256, name="attestation_sha256")
        _hex64(self.signature_sha256, name="signature_sha256")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation proof issuer system is invalid"
            )
        if type(self.attestation) is not PilotExecutionAdmissionAttestation:
            raise PilotExecutionAdmissionAttestationError(
                "exact PilotExecutionAdmissionAttestation is required"
            )
        attestation = PilotExecutionAdmissionAttestation.from_mapping(
            self.attestation.to_dict()
        )
        if attestation != self.attestation:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation proof replay identity mismatch"
            )
        if self.attestation_sha256 != attestation.sha256:
            raise PilotExecutionAdmissionAttestationError("attestation proof hash mismatch")
        _hex64(self.packet_sha256, name="packet_sha256")
        _hex64(self.start_receipt_sha256, name="start_receipt_sha256")
        if self.packet_sha256 != attestation.packet_sha256:
            raise PilotExecutionAdmissionAttestationError("proof packet hash mismatch")
        if self.start_receipt_sha256 != attestation.start_receipt_sha256:
            raise PilotExecutionAdmissionAttestationError(
                "proof start receipt binding mismatch"
            )
        if self.issuer_actor_id != attestation.packet.observer_actor_id:
            raise PilotExecutionAdmissionAttestationError(
                "attestation signer must be the packet observer actor"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        attested_at = _utc(attestation.attested_at_utc, name="attested_at_utc")
        if verified < attested_at:
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation proof timing is invalid"
            )
        expected_satisfied = attestation.all_checks_satisfied
        if (
            self.host_attestation_verified is not True
            or self.execution_admission_observed is not True
            or self.execution_admission_satisfied is not expected_satisfied
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
            or self.authority != PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY
        ):
            raise PilotExecutionAdmissionAttestationError(
                "execution-admission attestation proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExecutionAdmissionAttestationProof":
        data = dict(
            _strict(value, fields=_PROOF_FIELDS, name="execution-admission attestation proof")
        )
        attestation = data.get("attestation")
        if not isinstance(attestation, Mapping):
            raise PilotExecutionAdmissionAttestationError("attestation claim is invalid")
        data["attestation"] = PilotExecutionAdmissionAttestation.from_mapping(attestation)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "attestation_sha256": self.attestation_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "attestation": self.attestation.to_dict(),
            "verified_at_utc": self.verified_at_utc,
            "packet_sha256": self.packet_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "host_attestation_verified": self.host_attestation_verified,
            "execution_admission_observed": self.execution_admission_observed,
            "execution_admission_satisfied": self.execution_admission_satisfied,
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


def _verify_pilot_execution_admission_attestation(
    *,
    attestation: PilotExecutionAdmissionAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExecutionAdmissionAttestationProof:
    if type(attestation) is not PilotExecutionAdmissionAttestation:
        raise PilotExecutionAdmissionAttestationError(
            "exact PilotExecutionAdmissionAttestation is required"
        )
    replayed = PilotExecutionAdmissionAttestation.from_mapping(attestation.to_dict())
    if replayed != attestation or replayed.sha256 != attestation.sha256:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission attestation replay identity mismatch"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExecutionAdmissionAttestationError(
            "detached Ed25519 execution-admission attestation signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExecutionAdmissionAttestationError(
            "Ed25519 execution-admission attestation verifier is required"
        )
    if signature.issuer_system_id != PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != attestation.packet.observer_actor_id:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission attestation signer must be the packet observer actor"
        )
    if signature.signed_at_utc != attestation.attested_at_utc:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission signature time does not match claim"
        )
    verified_at = now_provider()
    if _utc(verified_at, name="verification time") < _utc(
        attestation.attested_at_utc, name="attested_at_utc"
    ):
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission verification predates claim"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=attestation.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission host authority verification failed"
        ) from exc
    if verified_payload_sha256 != attestation.sha256:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission verified payload hash mismatch"
        )
    return PilotExecutionAdmissionAttestationProof(
        attestation_sha256=attestation.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        attestation=attestation,
        verified_at_utc=verified_at,
        packet_sha256=attestation.packet_sha256,
        start_receipt_sha256=attestation.start_receipt_sha256,
        execution_admission_satisfied=attestation.all_checks_satisfied,
    )


def verify_pilot_execution_admission_attestation(
    *,
    attestation: PilotExecutionAdmissionAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExecutionAdmissionAttestationProof:
    if verifier is None:
        raise PilotExecutionAdmissionAttestationError(
            "execution-admission attestation verifier is unavailable outside production facade"
        )
    return _verify_pilot_execution_admission_attestation(
        attestation=attestation,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID",
    "RESULT_FIELDS",
    "PilotExecutionAdmissionAttestationError",
    "PilotExecutionAdmissionAttestation",
    "PilotExecutionAdmissionAttestationProof",
    "build_pilot_execution_admission_attestation",
    "verify_pilot_execution_admission_attestation",
]
