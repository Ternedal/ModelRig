"""Host-attested verification of one exact ADR-DC-022 preflight evidence packet.

ADR-DC-023 signs the complete ADR-DC-022 packet, including all twelve per-check
evidence digests.  It can establish only host attestation and preflight status;
it cannot integrate product code, register commands, start a pilot, mutate Git
or GitHub, or authorize remote/production activity.
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
from .improvement_pilot_runtime_preflight_observation import (
    PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY,
    PilotRuntimePreflightObservationPacket,
)

PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-runtime-preflight-attestation/v1"
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-runtime-preflight-attestation-proof/v1"
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY = (
    "dc-l16-runtime-preflight-attestation-claim-only"
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY = (
    "verified-dc-l16-runtime-preflight-attestation-only"
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-runtime-preflight-attestor-v1"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_RESULT_FIELDS = (
    "feature_flag_off_verified",
    "pilot_runtime_verified",
    "native_windows_isolation_verified",
    "trusted_git_closure_verified",
    "kill_switch_prearmed",
    "restart_revoke_prearmed",
    "network_write_block_verified",
    "credentials_absent_verified",
    "unattended_cadence_forbidden_verified",
    "off_state_import_block_verified",
    "exact_source_binding_verified",
    "receipt_binding_verified",
)

_ATTESTATION_FIELDS = {
    "schema",
    "packet",
    "packet_sha256",
    "attestation_id",
    "observer_host_id",
    "attested_at_utc",
    *_RESULT_FIELDS,
    "host_attestation_verified",
    "integration_ready",
    "preflight_observed",
    "preflight_satisfied",
    "pilot_start_authorized",
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
    "host_attestation_verified",
    "preflight_observed",
    "preflight_satisfied",
    "integration_ready",
    "pilot_start_authorized",
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


class PilotRuntimePreflightAttestationError(ValueError):
    """Runtime preflight attestation is malformed, untrusted or over-authorizing."""


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
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotRuntimePreflightAttestationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotRuntimePreflightAttestationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotRuntimePreflightAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotRuntimePreflightAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotRuntimePreflightAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotRuntimePreflightAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_packet(value: Any) -> PilotRuntimePreflightObservationPacket:
    if type(value) is not PilotRuntimePreflightObservationPacket:
        raise PilotRuntimePreflightAttestationError(
            "exact PilotRuntimePreflightObservationPacket is required"
        )
    if (
        value.authority != PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
        or value.observation_set_complete is not True
        or value.evidence_verified is not False
        or value.integration_ready is not False
        or value.preflight_observed is not False
        or value.preflight_satisfied is not False
        or value.pilot_start_authorized is not False
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
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight packet is not inert exact evidence"
        )
    try:
        replayed = PilotRuntimePreflightObservationPacket.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight packet replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight packet replay identity mismatch"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightAttestation:
    packet: PilotRuntimePreflightObservationPacket
    packet_sha256: str
    attestation_id: str
    observer_host_id: str
    attested_at_utc: str
    feature_flag_off_verified: bool
    pilot_runtime_verified: bool
    native_windows_isolation_verified: bool
    trusted_git_closure_verified: bool
    kill_switch_prearmed: bool
    restart_revoke_prearmed: bool
    network_write_block_verified: bool
    credentials_absent_verified: bool
    unattended_cadence_forbidden_verified: bool
    off_state_import_block_verified: bool
    exact_source_binding_verified: bool
    receipt_binding_verified: bool
    host_attestation_verified: bool = False
    integration_ready: bool = False
    preflight_observed: bool = False
    preflight_satisfied: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation schema is unsupported"
            )
        packet = _require_packet(self.packet)
        _hex64(self.packet_sha256, name="packet_sha256")
        if self.packet_sha256 != packet.sha256:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight packet hash mismatch"
            )
        _identifier(self.attestation_id, name="attestation_id")
        _identifier(self.observer_host_id, name="observer_host_id")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        observed = _utc(packet.observed_at_utc, name="packet observed_at_utc")
        if attested < observed:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation predates observation packet"
            )
        for name in _RESULT_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise PilotRuntimePreflightAttestationError(
                    f"{name} must be boolean"
                )
        if (
            self.host_attestation_verified is not False
            or self.integration_ready is not False
            or self.preflight_observed is not False
            or self.preflight_satisfied is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
        ):
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotRuntimePreflightAttestation":
        data = dict(
            _strict(
                value,
                fields=_ATTESTATION_FIELDS,
                name="runtime preflight attestation",
            )
        )
        packet = data.get("packet")
        if not isinstance(packet, Mapping):
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation packet is invalid"
            )
        data["packet"] = PilotRuntimePreflightObservationPacket.from_mapping(
            packet
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "packet": self.packet.to_dict(),
            "packet_sha256": self.packet_sha256,
            "attestation_id": self.attestation_id,
            "observer_host_id": self.observer_host_id,
            "attested_at_utc": self.attested_at_utc,
            **{name: getattr(self, name) for name in _RESULT_FIELDS},
            "host_attestation_verified": self.host_attestation_verified,
            "integration_ready": self.integration_ready,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "pilot_start_authorized": self.pilot_start_authorized,
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

    @property
    def all_checks_satisfied(self) -> bool:
        return all(getattr(self, name) is True for name in _RESULT_FIELDS)


def build_pilot_runtime_preflight_attestation(
    *,
    packet: PilotRuntimePreflightObservationPacket,
    attestation_id: str,
    observer_host_id: str,
    attested_at_utc: str,
    feature_flag_off_verified: bool,
    pilot_runtime_verified: bool,
    native_windows_isolation_verified: bool,
    trusted_git_closure_verified: bool,
    kill_switch_prearmed: bool,
    restart_revoke_prearmed: bool,
    network_write_block_verified: bool,
    credentials_absent_verified: bool,
    unattended_cadence_forbidden_verified: bool,
    off_state_import_block_verified: bool,
    exact_source_binding_verified: bool,
    receipt_binding_verified: bool,
) -> PilotRuntimePreflightAttestation:
    """Build exact externally-signable host-attestation bytes; grants no authority."""
    evidence = _require_packet(packet)
    return PilotRuntimePreflightAttestation(
        packet=evidence,
        packet_sha256=evidence.sha256,
        attestation_id=attestation_id,
        observer_host_id=observer_host_id,
        attested_at_utc=attested_at_utc,
        feature_flag_off_verified=feature_flag_off_verified,
        pilot_runtime_verified=pilot_runtime_verified,
        native_windows_isolation_verified=native_windows_isolation_verified,
        trusted_git_closure_verified=trusted_git_closure_verified,
        kill_switch_prearmed=kill_switch_prearmed,
        restart_revoke_prearmed=restart_revoke_prearmed,
        network_write_block_verified=network_write_block_verified,
        credentials_absent_verified=credentials_absent_verified,
        unattended_cadence_forbidden_verified=unattended_cadence_forbidden_verified,
        off_state_import_block_verified=off_state_import_block_verified,
        exact_source_binding_verified=exact_source_binding_verified,
        receipt_binding_verified=receipt_binding_verified,
    )


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightAttestationProof:
    attestation_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    attestation: PilotRuntimePreflightAttestation
    verified_at_utc: str
    packet_sha256: str
    host_attestation_verified: bool = True
    preflight_observed: bool = True
    preflight_satisfied: bool = False
    integration_ready: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof schema is unsupported"
            )
        _hex64(self.attestation_sha256, name="attestation_sha256")
        _hex64(self.signature_sha256, name="signature_sha256")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if (
            self.issuer_system_id
            != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
        ):
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof issuer system is invalid"
            )
        if type(self.attestation) is not PilotRuntimePreflightAttestation:
            raise PilotRuntimePreflightAttestationError(
                "exact PilotRuntimePreflightAttestation is required"
            )
        attestation = PilotRuntimePreflightAttestation.from_mapping(
            self.attestation.to_dict()
        )
        if attestation != self.attestation:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof replay identity mismatch"
            )
        if self.attestation_sha256 != attestation.sha256:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof hash mismatch"
            )
        _hex64(self.packet_sha256, name="packet_sha256")
        if self.packet_sha256 != attestation.packet_sha256:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof packet hash mismatch"
            )
        if self.issuer_actor_id != attestation.packet.observer_actor_id:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof signer mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        attested = _utc(attestation.attested_at_utc, name="attested_at_utc")
        if verified < attested:
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof timing is invalid"
            )
        expected_satisfied = attestation.all_checks_satisfied
        if (
            self.host_attestation_verified is not True
            or self.preflight_observed is not True
            or self.preflight_satisfied is not expected_satisfied
            or self.integration_ready is not False
            or self.pilot_start_authorized is not False
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
            != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY
        ):
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotRuntimePreflightAttestationProof":
        data = dict(
            _strict(
                value,
                fields=_PROOF_FIELDS,
                name="runtime preflight attestation proof",
            )
        )
        attestation = data.get("attestation")
        if not isinstance(attestation, Mapping):
            raise PilotRuntimePreflightAttestationError(
                "runtime preflight attestation proof claim is invalid"
            )
        data["attestation"] = PilotRuntimePreflightAttestation.from_mapping(
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
            "host_attestation_verified": self.host_attestation_verified,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "integration_ready": self.integration_ready,
            "pilot_start_authorized": self.pilot_start_authorized,
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


def _verify_pilot_runtime_preflight_attestation(
    *,
    attestation: PilotRuntimePreflightAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotRuntimePreflightAttestationProof:
    if type(attestation) is not PilotRuntimePreflightAttestation:
        raise PilotRuntimePreflightAttestationError(
            "exact PilotRuntimePreflightAttestation is required"
        )
    replayed = PilotRuntimePreflightAttestation.from_mapping(
        attestation.to_dict()
    )
    if replayed != attestation or replayed.sha256 != attestation.sha256:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation replay identity mismatch"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotRuntimePreflightAttestationError(
            "detached Ed25519 runtime preflight attestation signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotRuntimePreflightAttestationError(
            "Ed25519 runtime preflight attestation verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
    ):
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != attestation.packet.observer_actor_id:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation signer must be the packet observer actor"
        )
    if signature.signed_at_utc != attestation.attested_at_utc:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation signature time does not match claim"
        )
    verified_at = now_provider()
    if _utc(
        verified_at, name="runtime preflight attestation verification time"
    ) < _utc(attestation.attested_at_utc, name="attested_at_utc"):
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation verification predates claim"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=attestation.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation authority verification failed"
        ) from exc
    if verified_payload_sha256 != attestation.sha256:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation verified payload hash mismatch"
        )
    return PilotRuntimePreflightAttestationProof(
        attestation_sha256=attestation.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        attestation=attestation,
        verified_at_utc=verified_at,
        packet_sha256=attestation.packet_sha256,
        preflight_satisfied=attestation.all_checks_satisfied,
    )


def verify_pilot_runtime_preflight_attestation(
    *,
    attestation: PilotRuntimePreflightAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotRuntimePreflightAttestationProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PilotRuntimePreflightAttestationError(
            "runtime preflight attestation verifier is unavailable outside production facade"
        )
    return _verify_pilot_runtime_preflight_attestation(
        attestation=attestation,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID",
    "PilotRuntimePreflightAttestationError",
    "PilotRuntimePreflightAttestation",
    "PilotRuntimePreflightAttestationProof",
    "build_pilot_runtime_preflight_attestation",
    "verify_pilot_runtime_preflight_attestation",
]
