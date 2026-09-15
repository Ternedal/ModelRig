"""ADR-DC-048 human-signed authorization for one verified remote-publication candidate.

The claim binds the exact ADR-DC-047 manifest and a distinct one-shot remote
publication nonce. Verification proves human intent only; it selects no target
and grants no remote-write, push, PR, merge, release, deploy or production
activation authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_exact_task_local_commit_publication_requirements import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskLocalCommitPublicationRequirements,
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-human-authorization/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-remote-publication-human-authorization-claim-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-remote-publication-authorization-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-remote-publication-human-authority-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT = (
    "authorize-one-exact-verified-candidate-for-remote-publication"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "local_commit_publication_requirements_sha256",
    "local_commit_write_transaction_sha256",
    "write_reservation_sha256",
    "authorization_proof_sha256",
    "authorization_signature_sha256",
    "local_commit_object_identity_sha256",
    "execution_nonce_sha256",
    "local_write_nonce_sha256",
    "repository",
    "base_sha",
    "local_ref",
    "index_manifest_sha256",
    "root_tree_sha",
    "commit_payload_sha256",
    "predicted_commit_sha",
    "verified_tree_object_count",
    "verified_required_object_count",
    "gitlink_entry_count",
    "local_commit_verified_at_utc",
)


class PilotExactTaskRemotePublicationAuthorizationError(ValueError):
    """Remote-publication human authorization is malformed or unsafe."""


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
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization is not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "notes must be an array"
        )
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskRemotePublicationAuthorizationError("notes are invalid")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError("note is invalid")
    return items


def _require_requirements(
    value: Any,
) -> PilotExactTaskLocalCommitPublicationRequirements:
    if type(value) is not PilotExactTaskLocalCommitPublicationRequirements:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "exact ADR-DC-047 publication requirements are required"
        )
    try:
        replayed = PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-047 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-047 requirements identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY
        or value.local_commit_mechanically_verified is not True
        or value.publication_requirements_materialized is not True
        or value.separate_human_remote_publication_authorization_required is not True
        or value.remote_target_host_pinned_required is not True
        or value.remote_write_reservation_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization requires inert ADR-DC-047 requirements"
        )
    return value


def _require_live_requirements(
    value: Any,
) -> PilotExactTaskLocalCommitPublicationRequirements:
    exact = _require_requirements(value)
    if exact.verification_authenticated is not True:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization requires live ADR-DC-047 provenance"
        )
    return exact


def _binding(
    requirements: PilotExactTaskLocalCommitPublicationRequirements,
) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "local_commit_publication_requirements_sha256": exact.sha256,
        "local_commit_write_transaction_sha256": exact.local_commit_write_transaction_sha256,
        "write_reservation_sha256": exact.write_reservation_sha256,
        "authorization_proof_sha256": exact.authorization_proof_sha256,
        "authorization_signature_sha256": exact.authorization_signature_sha256,
        "local_commit_object_identity_sha256": exact.local_commit_object_identity_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "local_write_nonce_sha256": exact.local_write_nonce_sha256,
        "repository": exact.repository,
        "base_sha": exact.base_sha,
        "local_ref": exact.local_ref,
        "index_manifest_sha256": exact.index_manifest_sha256,
        "root_tree_sha": exact.root_tree_sha,
        "commit_payload_sha256": exact.commit_payload_sha256,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "verified_tree_object_count": exact.verified_tree_object_count,
        "verified_required_object_count": exact.verified_required_object_count,
        "gitlink_entry_count": exact.gitlink_entry_count,
        "local_commit_verified_at_utc": exact.verified_at_utc,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationAuthorization:
    authorization_id: str
    local_commit_publication_requirements: PilotExactTaskLocalCommitPublicationRequirements
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    write_reservation_sha256: str
    authorization_proof_sha256: str
    authorization_signature_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    repository: str
    base_sha: str
    local_ref: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    verified_tree_object_count: int
    verified_required_object_count: int
    gitlink_entry_count: int
    local_commit_verified_at_utc: str
    remote_publication_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    remote_publication_nonce_sha256: str
    notes: tuple[str, ...]
    human_remote_publication_intent: str = (
        PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT
    )
    one_shot_remote_publication_required: bool = True
    remote_target_host_pinned_required: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    human_remote_publication_authorization_verified: bool = False
    remote_publication_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization schema unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(
            self.local_commit_publication_requirements
        )
        for name in (
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "write_reservation_sha256",
            "authorization_proof_sha256",
            "authorization_signature_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        _actor(
            self.remote_publication_authorizer_actor_id,
            name="remote_publication_authorizer_actor_id",
        )
        _notes(self.notes)
        expected = _binding(requirements)
        mismatch = next(
            (
                name
                for name, item in expected.items()
                if getattr(self, name) != item
            ),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                f"remote publication authorization binding mismatch: {mismatch}"
            )
        if self.remote_publication_nonce_sha256 in {
            self.execution_nonce_sha256,
            self.local_write_nonce_sha256,
        }:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication nonce must be distinct from prior one-shot nonces"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        local_verified = _utc(
            self.local_commit_verified_at_utc,
            name="local_commit_verified_at_utc",
        )
        if authorized < local_verified or expires <= authorized:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization time window is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization window exceeds maximum"
            )
        if (
            self.human_remote_publication_intent
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization intent unsupported"
            )
        required_true = (
            "one_shot_remote_publication_required",
            "remote_target_host_pinned_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "human_remote_publication_authorization_verified",
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
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization requirements incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "claim cannot grant publication authority"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization authority unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["local_commit_publication_requirements"] = (
            self.local_commit_publication_requirements.to_dict()
        )
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationAuthorization":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization fields mismatch"
            )
        data = dict(value)
        if not isinstance(
            data["local_commit_publication_requirements"], Mapping
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "requirements must be an object"
            )
        if not isinstance(data["notes"], list):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "notes must be an array"
            )
        data["local_commit_publication_requirements"] = (
            PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
                data["local_commit_publication_requirements"]
            )
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskRemotePublicationAuthorization
    local_commit_publication_requirements_sha256: str
    predicted_commit_sha: str
    local_write_nonce_sha256: str
    remote_publication_nonce_sha256: str
    verified_at_utc: str
    one_shot_remote_publication_required: bool = True
    remote_target_host_pinned_required: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    human_remote_publication_authorization_verified: bool = True
    remote_publication_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof schema unsupported"
            )
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "local_commit_publication_requirements_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof issuer system invalid"
            )
        if type(self.authorization) is not PilotExactTaskRemotePublicationAuthorization:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "exact authorization is required"
            )
        replayed = PilotExactTaskRemotePublicationAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if (
            replayed != self.authorization
            or self.authorization_sha256 != self.authorization.sha256
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof authorization identity mismatch"
            )
        if (
            self.issuer_actor_id
            != self.authorization.remote_publication_authorizer_actor_id
            or self.local_commit_publication_requirements_sha256
            != self.authorization.local_commit_publication_requirements_sha256
            or self.predicted_commit_sha != self.authorization.predicted_commit_sha
            or self.local_write_nonce_sha256
            != self.authorization.local_write_nonce_sha256
            or self.remote_publication_nonce_sha256
            != self.authorization.remote_publication_nonce_sha256
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof binding mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(
            self.authorization.authorized_at_utc, name="authorized_at_utc"
        )
        expires = _utc(
            self.authorization.expires_at_utc, name="expires_at_utc"
        )
        if verified < authorized or verified > expires:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof verified outside authorization window"
            )
        required_true = (
            "one_shot_remote_publication_required",
            "remote_target_host_pinned_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
            "human_remote_publication_authorization_verified",
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
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof cannot grant remote authority"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof authority unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["authorization"] = self.authorization.to_dict()
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationAuthorizationProof":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "proof fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["authorization"], Mapping):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization must be an object"
            )
        data["authorization"] = PilotExactTaskRemotePublicationAuthorization.from_mapping(
            data["authorization"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def build_pilot_exact_task_remote_publication_authorization(
    *,
    local_commit_publication_requirements: PilotExactTaskLocalCommitPublicationRequirements,
    authorization_id: str,
    remote_publication_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    remote_publication_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskRemotePublicationAuthorization:
    requirements = _require_live_requirements(
        local_commit_publication_requirements
    )
    return PilotExactTaskRemotePublicationAuthorization(
        authorization_id=authorization_id,
        local_commit_publication_requirements=requirements,
        remote_publication_authorizer_actor_id=remote_publication_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        remote_publication_nonce_sha256=remote_publication_nonce_sha256,
        notes=_notes(notes),
        **_binding(requirements),
    )


def _verify_pilot_exact_task_remote_publication_authorization(
    *,
    local_commit_publication_requirements: PilotExactTaskLocalCommitPublicationRequirements,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    requirements = _require_live_requirements(
        local_commit_publication_requirements
    )
    if type(authorization) is not PilotExactTaskRemotePublicationAuthorization:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "exact authorization is required"
        )
    replayed = PilotExactTaskRemotePublicationAuthorization.from_mapping(
        authorization.to_dict()
    )
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization replay identity mismatch"
        )
    if (
        authorization.local_commit_publication_requirements is not requirements
        or authorization.local_commit_publication_requirements_sha256
        != requirements.sha256
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization is not bound to supplied live requirements"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "detached Ed25519 signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "Ed25519 verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "signature belongs to another issuer system"
        )
    if (
        signature.issuer_actor_id
        != authorization.remote_publication_authorizer_actor_id
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "signature actor mismatch"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "signature time mismatch"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization is not currently valid"
        )
    try:
        payload_sha = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "human remote publication signature verification failed"
        ) from exc
    if payload_sha != authorization.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "verified payload hash mismatch"
        )
    return PilotExactTaskRemotePublicationAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        local_commit_publication_requirements_sha256=requirements.sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        local_write_nonce_sha256=requirements.local_write_nonce_sha256,
        remote_publication_nonce_sha256=authorization.remote_publication_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_remote_publication_authorization(
    *,
    local_commit_publication_requirements: PilotExactTaskLocalCommitPublicationRequirements,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    raise PilotExactTaskRemotePublicationAuthorizationError(
        "production remote-publication verification boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskRemotePublicationAuthorizationError",
    "PilotExactTaskRemotePublicationAuthorization",
    "PilotExactTaskRemotePublicationAuthorizationProof",
    "build_pilot_exact_task_remote_publication_authorization",
    "verify_pilot_exact_task_remote_publication_authorization",
]
