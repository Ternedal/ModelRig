"""Host-attested verification of one exact ADR-DC-031 revalidation packet.

ADR-DC-032 signs the complete ADR-DC-031 packet plus one boolean result for each
of its 25 fresh revalidation gates.  A verified signature can establish only
that those checks were host-attested for the exact packet.  It deliberately does
not grant execution admission, task execution, local commit, remote mutation,
release, deploy or production activation authority.
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
from .improvement_pilot_exact_task_execution_revalidation_observation import (
    PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY,
    PilotExactTaskExecutionRevalidationObservationPacket,
)

PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-revalidation-attestation/v1"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-revalidation-attestation-proof/v1"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY = (
    "dc-l16-exact-task-execution-revalidation-attestation-claim-only"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY = (
    "verified-dc-l16-exact-task-execution-revalidation-attestation-only"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-task-execution-revalidation-attestor-v1"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

RESULT_FIELDS = (
    "fresh_host_attestation_reverified",
    "fresh_live_consumption_revalidated",
    "fresh_human_task_execution_authorization_verified",
    "one_shot_execution_nonce_verified",
    "host_local_execution_admission_ledger_verified",
    "exact_allowlisted_task_registry_entry_verified",
    "exact_selected_task_verified",
    "canonical_workspace_revalidated",
    "exact_source_base_head_binding_verified",
    "exact_toolchain_binding_verified",
    "feature_flag_enabled_reobserved",
    "native_windows_isolation_revalidated",
    "trusted_git_closure_revalidated",
    "kill_switch_armed_revalidated",
    "revoke_not_asserted_revalidated",
    "restart_recovery_revalidated",
    "network_write_blocked_revalidated",
    "credentials_absent_revalidated",
    "general_shell_forbidden_verified",
    "model_defined_commands_forbidden_verified",
    "unattended_cadence_forbidden_verified",
    "exact_fixed_command_plan_verified",
    "bounded_execution_budget_verified",
    "manual_operator_invocation_verified",
    "post_execution_receipt_capability_verified",
)

_ATTESTATION_FIELDS = {
    "schema",
    "packet",
    "packet_sha256",
    "execution_authorization_proof_sha256",
    "execution_authorization_signature_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_signature_sha256",
    "execution_nonce_sha256",
    "attestation_id",
    "observer_host_id",
    "attested_at_utc",
    *RESULT_FIELDS,
    "host_attestation_verified",
    "execution_revalidation_observed",
    "execution_revalidation_satisfied",
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
    "execution_authorization_proof_sha256",
    "execution_authorization_signature_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_signature_sha256",
    "execution_nonce_sha256",
    "host_attestation_verified",
    "execution_revalidation_observed",
    "execution_revalidation_satisfied",
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


class PilotExactTaskExecutionRevalidationAttestationError(ValueError):
    """Exact-task revalidation attestation is malformed, untrusted or unsafe."""


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
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "exact-task revalidation attestation is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} fields mismatch"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} is invalid"
        )
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} is invalid"
        )
    if value == "0" * 64:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} must not be a placeholder"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_packet(
    value: Any,
) -> PilotExactTaskExecutionRevalidationObservationPacket:
    if type(value) is not PilotExactTaskExecutionRevalidationObservationPacket:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "exact ADR-DC-031 PilotExactTaskExecutionRevalidationObservationPacket is required"
        )
    try:
        replayed = PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "ADR-DC-031 packet replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "ADR-DC-031 packet replay identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY
        or value.observation_set_complete is not True
        or value.human_authorization_proof_bound is not True
        or value.evidence_verified is not False
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
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "ADR-DC-031 packet is not inert exact revalidation evidence"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionRevalidationAttestation:
    packet: PilotExactTaskExecutionRevalidationObservationPacket
    packet_sha256: str
    execution_authorization_proof_sha256: str
    execution_authorization_signature_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_signature_sha256: str
    execution_nonce_sha256: str
    attestation_id: str
    observer_host_id: str
    attested_at_utc: str
    fresh_host_attestation_reverified: bool
    fresh_live_consumption_revalidated: bool
    fresh_human_task_execution_authorization_verified: bool
    one_shot_execution_nonce_verified: bool
    host_local_execution_admission_ledger_verified: bool
    exact_allowlisted_task_registry_entry_verified: bool
    exact_selected_task_verified: bool
    canonical_workspace_revalidated: bool
    exact_source_base_head_binding_verified: bool
    exact_toolchain_binding_verified: bool
    feature_flag_enabled_reobserved: bool
    native_windows_isolation_revalidated: bool
    trusted_git_closure_revalidated: bool
    kill_switch_armed_revalidated: bool
    revoke_not_asserted_revalidated: bool
    restart_recovery_revalidated: bool
    network_write_blocked_revalidated: bool
    credentials_absent_revalidated: bool
    general_shell_forbidden_verified: bool
    model_defined_commands_forbidden_verified: bool
    unattended_cadence_forbidden_verified: bool
    exact_fixed_command_plan_verified: bool
    bounded_execution_budget_verified: bool
    manual_operator_invocation_verified: bool
    post_execution_receipt_capability_verified: bool
    host_attestation_verified: bool = False
    execution_revalidation_observed: bool = False
    execution_revalidation_satisfied: bool = False
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "exact-task revalidation attestation schema is unsupported"
            )
        packet = _require_packet(self.packet)
        for name in (
            "packet_sha256",
            "execution_authorization_proof_sha256",
            "execution_authorization_signature_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "execution_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        expected = {
            "packet_sha256": packet.sha256,
            "execution_authorization_proof_sha256": (
                packet.execution_authorization_proof_sha256
            ),
            "execution_authorization_signature_sha256": (
                packet.execution_authorization_signature_sha256
            ),
            "admission_attestation_proof_sha256": (
                packet.admission_attestation_proof_sha256
            ),
            "admission_attestation_signature_sha256": (
                packet.admission_attestation_signature_sha256
            ),
            "execution_nonce_sha256": packet.execution_nonce_sha256,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                f"revalidation attestation binding mismatch: {mismatch}"
            )
        _identifier(self.attestation_id, name="attestation_id")
        _identifier(self.observer_host_id, name="observer_host_id")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        observed = _utc(packet.observed_at_utc, name="packet observed_at_utc")
        expires = _utc(
            packet.execution_authorization_proof.authorization.expires_at_utc,
            name="execution authorization expires_at_utc",
        )
        if attested < observed:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation predates observation packet"
            )
        if attested > expires:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation is after human authorization expiry"
            )
        authorizer = (
            packet.execution_authorization_proof.authorization
            .execution_authorizer_actor_id
        )
        if packet.observer_actor_id == authorizer:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation observer must be distinct from human execution authorizer"
            )
        for name in RESULT_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise PilotExactTaskExecutionRevalidationAttestationError(
                    f"{name} must be boolean"
                )
        if (
            self.host_attestation_verified is not False
            or self.execution_revalidation_observed is not False
            or self.execution_revalidation_satisfied is not False
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
            != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY
        ):
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation authority boundary is invalid"
            )

    @property
    def all_checks_satisfied(self) -> bool:
        return all(getattr(self, name) is True for name in RESULT_FIELDS)

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskExecutionRevalidationAttestation":
        data = dict(
            _strict(value, fields=_ATTESTATION_FIELDS, name="revalidation attestation")
        )
        packet = data.get("packet")
        if not isinstance(packet, Mapping):
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation packet is invalid"
            )
        data["packet"] = (
            PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(packet)
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "packet": self.packet.to_dict(),
            "packet_sha256": self.packet_sha256,
            "execution_authorization_proof_sha256": (
                self.execution_authorization_proof_sha256
            ),
            "execution_authorization_signature_sha256": (
                self.execution_authorization_signature_sha256
            ),
            "admission_attestation_proof_sha256": (
                self.admission_attestation_proof_sha256
            ),
            "admission_attestation_signature_sha256": (
                self.admission_attestation_signature_sha256
            ),
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "attestation_id": self.attestation_id,
            "observer_host_id": self.observer_host_id,
            "attested_at_utc": self.attested_at_utc,
            **{name: getattr(self, name) for name in RESULT_FIELDS},
            "host_attestation_verified": self.host_attestation_verified,
            "execution_revalidation_observed": self.execution_revalidation_observed,
            "execution_revalidation_satisfied": self.execution_revalidation_satisfied,
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


def build_pilot_exact_task_execution_revalidation_attestation(
    *,
    packet: PilotExactTaskExecutionRevalidationObservationPacket,
    attestation_id: str,
    observer_host_id: str,
    attested_at_utc: str,
    results: Mapping[str, bool],
) -> PilotExactTaskExecutionRevalidationAttestation:
    exact_packet = _require_packet(packet)
    if not isinstance(results, Mapping) or set(results) != set(RESULT_FIELDS):
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation attestation result set mismatch"
        )
    return PilotExactTaskExecutionRevalidationAttestation(
        packet=exact_packet,
        packet_sha256=exact_packet.sha256,
        execution_authorization_proof_sha256=(
            exact_packet.execution_authorization_proof_sha256
        ),
        execution_authorization_signature_sha256=(
            exact_packet.execution_authorization_signature_sha256
        ),
        admission_attestation_proof_sha256=(
            exact_packet.admission_attestation_proof_sha256
        ),
        admission_attestation_signature_sha256=(
            exact_packet.admission_attestation_signature_sha256
        ),
        execution_nonce_sha256=exact_packet.execution_nonce_sha256,
        attestation_id=attestation_id,
        observer_host_id=observer_host_id,
        attested_at_utc=attested_at_utc,
        **{name: results[name] for name in RESULT_FIELDS},
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionRevalidationAttestationProof:
    attestation_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    attestation: PilotExactTaskExecutionRevalidationAttestation
    verified_at_utc: str
    packet_sha256: str
    execution_authorization_proof_sha256: str
    execution_authorization_signature_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_signature_sha256: str
    execution_nonce_sha256: str
    host_attestation_verified: bool = True
    execution_revalidation_observed: bool = True
    execution_revalidation_satisfied: bool = False
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
    authority: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof schema is unsupported"
            )
        for name in (
            "attestation_sha256",
            "signature_sha256",
            "packet_sha256",
            "execution_authorization_proof_sha256",
            "execution_authorization_signature_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "execution_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
        ):
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof issuer system is invalid"
            )
        if type(self.attestation) is not PilotExactTaskExecutionRevalidationAttestation:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "exact revalidation attestation is required"
            )
        replayed = PilotExactTaskExecutionRevalidationAttestation.from_mapping(
            self.attestation.to_dict()
        )
        if replayed != self.attestation:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof replay identity mismatch"
            )
        if self.attestation_sha256 != replayed.sha256:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof hash mismatch"
            )
        expected = {
            "packet_sha256": replayed.packet_sha256,
            "execution_authorization_proof_sha256": (
                replayed.execution_authorization_proof_sha256
            ),
            "execution_authorization_signature_sha256": (
                replayed.execution_authorization_signature_sha256
            ),
            "admission_attestation_proof_sha256": (
                replayed.admission_attestation_proof_sha256
            ),
            "admission_attestation_signature_sha256": (
                replayed.admission_attestation_signature_sha256
            ),
            "execution_nonce_sha256": replayed.execution_nonce_sha256,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                f"revalidation proof binding mismatch: {mismatch}"
            )
        if self.issuer_actor_id != replayed.packet.observer_actor_id:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation signer must be packet observer actor"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        attested = _utc(replayed.attested_at_utc, name="attested_at_utc")
        expires = _utc(
            replayed.packet.execution_authorization_proof.authorization.expires_at_utc,
            name="execution authorization expires_at_utc",
        )
        if verified < attested or verified > expires:
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof verified outside valid time window"
            )
        expected_satisfied = replayed.all_checks_satisfied
        if (
            self.host_attestation_verified is not True
            or self.execution_revalidation_observed is not True
            or self.execution_revalidation_satisfied is not expected_satisfied
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
            != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY
        ):
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskExecutionRevalidationAttestationProof":
        data = dict(
            _strict(value, fields=_PROOF_FIELDS, name="revalidation attestation proof")
        )
        attestation = data.get("attestation")
        if not isinstance(attestation, Mapping):
            raise PilotExactTaskExecutionRevalidationAttestationError(
                "revalidation attestation claim is invalid"
            )
        data["attestation"] = PilotExactTaskExecutionRevalidationAttestation.from_mapping(
            attestation
        )
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
            "execution_authorization_proof_sha256": (
                self.execution_authorization_proof_sha256
            ),
            "execution_authorization_signature_sha256": (
                self.execution_authorization_signature_sha256
            ),
            "admission_attestation_proof_sha256": (
                self.admission_attestation_proof_sha256
            ),
            "admission_attestation_signature_sha256": (
                self.admission_attestation_signature_sha256
            ),
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "host_attestation_verified": self.host_attestation_verified,
            "execution_revalidation_observed": self.execution_revalidation_observed,
            "execution_revalidation_satisfied": self.execution_revalidation_satisfied,
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


def _verify_pilot_exact_task_execution_revalidation_attestation(
    *,
    attestation: PilotExactTaskExecutionRevalidationAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskExecutionRevalidationAttestationProof:
    if type(attestation) is not PilotExactTaskExecutionRevalidationAttestation:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "exact revalidation attestation is required"
        )
    replayed = PilotExactTaskExecutionRevalidationAttestation.from_mapping(
        attestation.to_dict()
    )
    if replayed != attestation or replayed.sha256 != attestation.sha256:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation attestation replay identity mismatch"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "detached Ed25519 revalidation attestation signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "Ed25519 revalidation attestation verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
    ):
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != attestation.packet.observer_actor_id:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation attestation signer must be packet observer actor"
        )
    if signature.signed_at_utc != attestation.attested_at_utc:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation signature time does not match claim"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verification time")
    attested = _utc(attestation.attested_at_utc, name="attested_at_utc")
    expires = _utc(
        attestation.packet.execution_authorization_proof.authorization.expires_at_utc,
        name="execution authorization expires_at_utc",
    )
    if verified < attested or verified > expires:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation attestation verification is outside valid time window"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=attestation.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation host authority verification failed"
        ) from exc
    if verified_payload_sha256 != attestation.sha256:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation verified payload hash mismatch"
        )
    return PilotExactTaskExecutionRevalidationAttestationProof(
        attestation_sha256=attestation.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        attestation=attestation,
        verified_at_utc=verified_at,
        packet_sha256=attestation.packet_sha256,
        execution_authorization_proof_sha256=(
            attestation.execution_authorization_proof_sha256
        ),
        execution_authorization_signature_sha256=(
            attestation.execution_authorization_signature_sha256
        ),
        admission_attestation_proof_sha256=(
            attestation.admission_attestation_proof_sha256
        ),
        admission_attestation_signature_sha256=(
            attestation.admission_attestation_signature_sha256
        ),
        execution_nonce_sha256=attestation.execution_nonce_sha256,
        execution_revalidation_satisfied=attestation.all_checks_satisfied,
    )


def verify_pilot_exact_task_execution_revalidation_attestation(
    *,
    attestation: PilotExactTaskExecutionRevalidationAttestation,
    signature: DetachedEd25519AuthoritySignature,
    execution_authorization_signature: DetachedEd25519AuthoritySignature | None = None,
    admission_attestation_signature: DetachedEd25519AuthoritySignature | None = None,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskExecutionRevalidationAttestationProof:
    del execution_authorization_signature, admission_attestation_signature
    if verifier is None:
        raise PilotExactTaskExecutionRevalidationAttestationError(
            "revalidation attestation verifier is unavailable outside production facade"
        )
    return _verify_pilot_exact_task_execution_revalidation_attestation(
        attestation=attestation,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID",
    "RESULT_FIELDS",
    "PilotExactTaskExecutionRevalidationAttestationError",
    "PilotExactTaskExecutionRevalidationAttestation",
    "PilotExactTaskExecutionRevalidationAttestationProof",
    "build_pilot_exact_task_execution_revalidation_attestation",
    "verify_pilot_exact_task_execution_revalidation_attestation",
]
