"""ADR-DC-049 host-pinned target attestation for one remote-publication proof.

This boundary binds one freshly reverified ADR-DC-048 human authorization to a
host-admin-controlled remote target policy and derives one exact destination ref
from the signed remote-publication nonce. It performs no network access and
never grants push, PR, merge, release, deploy, or production authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .improvement_pilot_exact_task_remote_publication_authorization import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskRemotePublicationAuthorizationProof,
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-target-policy/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-target-attestation/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-remote-publication-target-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE = (
    "one-host-pinned-remote-target-and-destination-ref-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER = "github"
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST = "github.com"
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY = "Ternedal/ModelRig"
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL = (
    "https://github.com/Ternedal/ModelRig.git"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE = (
    "refs/heads/agent/rsi/remote-candidate/"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION = (
    "signed-remote-publication-nonce-hex-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DESTINATION_REF = re.compile(
    r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$"
)


class PilotExactTaskRemotePublicationTargetAttestationError(ValueError):
    """The remote-publication target is not exact, host-pinned, or safe."""


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
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "remote target evidence is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationTargetPolicy:
    policy_epoch: int
    provider: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER
    remote_host: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST
    remote_repository: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY
    canonical_remote_url: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL
    destination_ref_namespace: str = (
        PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE
    )
    destination_ref_derivation: str = (
        PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION
    )
    remote_state_observation_required: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    expected_old_remote_sha_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target policy schema is unsupported"
            )
        if (
            isinstance(self.policy_epoch, bool)
            or not isinstance(self.policy_epoch, int)
            or self.policy_epoch < 1
        ):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target policy epoch is invalid"
            )
        fixed = {
            "provider": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER,
            "remote_host": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST,
            "remote_repository": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY,
            "canonical_remote_url": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL,
            "destination_ref_namespace": PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE,
            "destination_ref_derivation": PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION,
        }
        mismatch = next(
            (name for name, expected in fixed.items() if getattr(self, name) != expected),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                f"remote target policy is not host-pinned: {mismatch}"
            )
        required_true = (
            "remote_state_observation_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "expected_old_remote_sha_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target policy weakens required publication controls"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationTargetPolicy":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target policy must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target policy fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _require_proof(
    value: Any,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    if type(value) is not PilotExactTaskRemotePublicationAuthorizationProof:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "exact ADR-DC-048 remote-publication authorization proof is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "ADR-DC-048 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "ADR-DC-048 proof identity mismatch"
        )
    authorization = value.authorization
    requirements = authorization.local_commit_publication_requirements
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_remote_publication_authorization_verified is not True
        or value.one_shot_remote_publication_required is not True
        or value.remote_target_host_pinned_required is not True
        or value.remote_write_reservation_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_publication_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or authorization.repository != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY
        or requirements.repository != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY
        or authorization.predicted_commit_sha != value.predicted_commit_sha
        or authorization.remote_publication_nonce_sha256
        != value.remote_publication_nonce_sha256
    ):
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "target attestation requires one inert verified ADR-DC-048 proof"
        )
    return value


def _require_live_proof(
    value: Any,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    proof = _require_proof(value)
    requirements = proof.authorization.local_commit_publication_requirements
    if requirements.verification_authenticated is not True:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "target attestation requires live ADR-DC-047 provenance"
        )
    return proof


def require_fresh_remote_publication_authorization_proof_identity(
    supplied: PilotExactTaskRemotePublicationAuthorizationProof,
    fresh: PilotExactTaskRemotePublicationAuthorizationProof,
) -> None:
    left = _require_proof(supplied).to_dict()
    right = _require_proof(fresh).to_dict()
    left.pop("verified_at_utc")
    right.pop("verified_at_utc")
    if left != right:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "fresh ADR-DC-048 proof does not match the supplied authorization"
        )


def _destination_ref(
    policy: PilotExactTaskRemotePublicationTargetPolicy,
    remote_publication_nonce_sha256: str,
) -> str:
    target = policy.destination_ref_namespace + _hex64(
        remote_publication_nonce_sha256,
        name="remote_publication_nonce_sha256",
    )
    if _DESTINATION_REF.fullmatch(target) is None:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "derived destination ref is outside the host-pinned namespace"
        )
    return target


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            PilotExactTaskRemotePublicationAuthorizationProof,
        ],
    ] = {}

    def mark(
        attestation: Any,
        proof: PilotExactTaskRemotePublicationAuthorizationProof,
    ) -> None:
        key = id(attestation)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            attestation.sha256,
            weakref.ref(attestation, cleanup),
            proof,
        )

    def get(attestation: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(attestation))
        if entry is None:
            return None
        pid, digest, attestation_ref, proof = entry
        if (
            pid != os.getpid()
            or attestation_ref() is not attestation
            or attestation.sha256 != digest
            or proof.sha256 != attestation.authorization_proof_sha256
            or proof.authorization.local_commit_publication_requirements.verification_authenticated
            is not True
        ):
            return None
        return MappingProxyType({"remote_publication_authorization_proof": proof})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_target_attestation_authenticated,
    _get_live_remote_publication_target_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationTargetAttestation:
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    repository: str
    target_policy_sha256: str
    target_policy_epoch: int
    target_provider: str
    target_host: str
    target_repository: str
    canonical_remote_url: str
    destination_ref: str
    attested_at_utc: str
    human_remote_publication_authorization_verified: bool = True
    remote_target_host_pinned: bool = True
    destination_ref_derived_from_signed_nonce: bool = True
    remote_state_observation_required: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    expected_old_remote_sha_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    remote_publication_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY
    attestation_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation schema is unsupported"
            )
        if self.attestation_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation scope is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation authority is unsupported"
            )
        for name in (
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "target_policy_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if self.repository != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "attested repository is unsupported"
            )
        if (
            isinstance(self.target_policy_epoch, bool)
            or not isinstance(self.target_policy_epoch, int)
            or self.target_policy_epoch < 1
        ):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "target policy epoch is invalid"
            )
        fixed = {
            "target_provider": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER,
            "target_host": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST,
            "target_repository": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY,
            "canonical_remote_url": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL,
        }
        mismatch = next(
            (name for name, expected in fixed.items() if getattr(self, name) != expected),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                f"attested target is not host-pinned: {mismatch}"
            )
        expected_ref = (
            PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE
            + self.remote_publication_nonce_sha256
        )
        if self.destination_ref != expected_ref or _DESTINATION_REF.fullmatch(
            self.destination_ref
        ) is None:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "destination ref is not derived from the signed publication nonce"
            )
        _utc(self.attested_at_utc, name="attested_at_utc")
        required_true = (
            "human_remote_publication_authorization_verified",
            "remote_target_host_pinned",
            "destination_ref_derived_from_signed_nonce",
            "remote_state_observation_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "expected_old_remote_sha_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation cannot grant publication authority"
            )

    @property
    def target_attestation_authenticated(self) -> bool:
        return _get_live_remote_publication_target_attestation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationTargetAttestation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls, text: str
    ) -> "PilotExactTaskRemotePublicationTargetAttestation":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskRemotePublicationTargetAttestationError(
                "remote target attestation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_remote_publication_target(
    *,
    authorization_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    fresh_authorization_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    target_policy: PilotExactTaskRemotePublicationTargetPolicy,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationTargetAttestation:
    proof = _require_live_proof(authorization_proof)
    fresh = _require_live_proof(fresh_authorization_proof)
    require_fresh_remote_publication_authorization_proof_identity(proof, fresh)
    if type(target_policy) is not PilotExactTaskRemotePublicationTargetPolicy:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "exact host remote target policy is required"
        )
    replayed_policy = PilotExactTaskRemotePublicationTargetPolicy.from_mapping(
        target_policy.to_dict()
    )
    if replayed_policy != target_policy or replayed_policy.sha256 != target_policy.sha256:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "remote target policy replay identity mismatch"
        )
    attested_at = now_provider()
    attested = _utc(attested_at, name="attested_at_utc")
    verified = _utc(fresh.verified_at_utc, name="fresh proof verified_at_utc")
    authorized = _utc(
        fresh.authorization.authorized_at_utc,
        name="authorization authorized_at_utc",
    )
    expires = _utc(
        fresh.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    )
    if attested < verified or attested < authorized or attested > expires:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "human remote-publication authorization is not valid for target attestation"
        )
    requirements = fresh.authorization.local_commit_publication_requirements
    destination_ref = _destination_ref(
        target_policy,
        fresh.remote_publication_nonce_sha256,
    )
    result = PilotExactTaskRemotePublicationTargetAttestation(
        authorization_proof_sha256=fresh.sha256,
        authorization_sha256=fresh.authorization_sha256,
        authorization_signature_sha256=fresh.signature_sha256,
        local_commit_publication_requirements_sha256=(
            fresh.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            requirements.local_commit_write_transaction_sha256
        ),
        local_commit_object_identity_sha256=(
            requirements.local_commit_object_identity_sha256
        ),
        execution_nonce_sha256=requirements.execution_nonce_sha256,
        local_write_nonce_sha256=fresh.local_write_nonce_sha256,
        remote_publication_nonce_sha256=fresh.remote_publication_nonce_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        repository=requirements.repository,
        target_policy_sha256=target_policy.sha256,
        target_policy_epoch=target_policy.policy_epoch,
        target_provider=target_policy.provider,
        target_host=target_policy.remote_host,
        target_repository=target_policy.remote_repository,
        canonical_remote_url=target_policy.canonical_remote_url,
        destination_ref=destination_ref,
        attested_at_utc=attested_at,
    )
    _mark_remote_publication_target_attestation_authenticated(result, fresh)
    if result.target_attestation_authenticated is not True:
        raise PilotExactTaskRemotePublicationTargetAttestationError(
            "remote target attestation lost live authorization provenance"
        )
    return result


def attest_pilot_exact_task_remote_publication_target(
    *,
    authorization_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    authorization_signature: Any,
) -> PilotExactTaskRemotePublicationTargetAttestation:
    raise PilotExactTaskRemotePublicationTargetAttestationError(
        "production remote target attestation boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION",
    "PilotExactTaskRemotePublicationTargetAttestationError",
    "PilotExactTaskRemotePublicationTargetPolicy",
    "PilotExactTaskRemotePublicationTargetAttestation",
    "attest_pilot_exact_task_remote_publication_target",
]
