"""ADR-DC-051 human-signed authorization for one exact remote publication."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from . import improvement_pilot_exact_task_remote_head_observation as observation_boundary
from .improvement_pilot_exact_task_remote_head_observation import (
    PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY,
    PilotExactTaskRemoteHeadObservation,
)
from .improvement_pilot_exact_task_remote_publication_requirements import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT,
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS,
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-human-authorization/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-task-remote-publication-human-authorization-claim-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-task-remote-publication-authorization-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-human-authority-v1"
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskRemotePublicationAuthorizationError(ValueError):
    """Exact remote-publication human authorization is malformed or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication authorization is not canonical JSON"
        ) from exc


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


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization notes must be an array"
        )
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization notes are invalid"
        )
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2048
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization note is invalid"
            )
    return items


def _replay_observation(value: Any) -> PilotExactTaskRemoteHeadObservation:
    if type(value) is not PilotExactTaskRemoteHeadObservation:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "exact ADR-DC-050 remote-head observation is required"
        )
    try:
        replayed = PilotExactTaskRemoteHeadObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-050 observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-050 observation replay identity mismatch"
        )
    required_true = (
        "network_access_performed",
        "remote_head_observed",
        "remote_head_stable_across_double_observation",
        "local_commit_state_matched",
        "exact_remote_repository_matched",
        "exact_destination_ref_matched",
        "fast_forward_candidate",
        "fresh_human_remote_publication_authorization_required",
        "fresh_remote_head_revalidation_before_push_required",
    )
    forced_false = (
        "credential_material_present",
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
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization requires one inert ADR-DC-050 observation"
        )
    return value


def _require_live_observation(value: Any) -> PilotExactTaskRemoteHeadObservation:
    exact = _replay_observation(value)
    if (
        exact.observation_authenticated is not True
        or observation_boundary._get_live_remote_head_observation_inputs(exact) is None
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization requires live ADR-DC-050 provenance"
        )
    return exact


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationAuthorization:
    authorization_id: str
    remote_head_observation: PilotExactTaskRemoteHeadObservation
    remote_head_observation_sha256: str
    observation_key_sha256: str
    requirements_sha256: str
    local_commit_sha: str
    destination_ref: str
    remote_head_present: bool
    remote_head_sha: str | None
    publication_mode: str
    remote_publication_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    remote_publication_nonce_sha256: str
    notes: tuple[str, ...]
    human_remote_publication_intent: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT
    one_shot_remote_publication_required: bool = True
    fresh_remote_head_revalidation_before_push_required: bool = True
    remote_publication_authorization_consumed: bool = False
    human_remote_publication_authorization_verified: bool = False
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
        observation = _replay_observation(self.remote_head_observation)
        for name in (
            "remote_head_observation_sha256",
            "observation_key_sha256",
            "requirements_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.local_commit_sha, name="local_commit_sha")
        if self.remote_head_sha is not None:
            _hex40(self.remote_head_sha, name="remote_head_sha")
        _actor(
            self.remote_publication_authorizer_actor_id,
            name="remote_publication_authorizer_actor_id",
        )
        expected = {
            "remote_head_observation_sha256": observation.sha256,
            "observation_key_sha256": observation.observation_key_sha256,
            "requirements_sha256": observation.requirements_sha256,
            "local_commit_sha": observation.local_commit_sha,
            "destination_ref": observation.destination_ref,
            "remote_head_present": observation.remote_head_present,
            "remote_head_sha": observation.remote_head_sha,
            "publication_mode": observation.publication_mode,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                f"authorization binding mismatch: {mismatch}"
            )
        if self.remote_publication_nonce_sha256 in {
            self.remote_head_observation_sha256,
            self.observation_key_sha256,
            self.requirements_sha256,
        }:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote-publication nonce must be fresh and distinct"
            )
        _notes(self.notes)
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        observed = _utc(
            observation.observation_completed_at_utc,
            name="observation_completed_at_utc",
        )
        if authorized < observed or expires <= authorized:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization time window is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization window exceeds maximum"
            )
        if (
            self.human_remote_publication_intent
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization intent unsupported"
            )
        if (
            self.one_shot_remote_publication_required is not True
            or self.fresh_remote_head_revalidation_before_push_required is not True
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "one-shot authorization and fresh pre-push revalidation are required"
            )
        forced_false = (
            "remote_publication_authorization_consumed",
            "human_remote_publication_authorization_verified",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "claim cannot grant or consume remote authority"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization authority unsupported"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        result["remote_head_observation"] = self.remote_head_observation.to_dict()
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationAuthorization":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization fields mismatch"
            )
        mapped = dict(value)
        try:
            mapped["remote_head_observation"] = (
                PilotExactTaskRemoteHeadObservation.from_mapping(
                    mapped["remote_head_observation"]
                )
            )
            mapped["notes"] = tuple(mapped["notes"])
        except Exception as exc:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization nested evidence is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_authorization(
    value: Any,
) -> PilotExactTaskRemotePublicationAuthorization:
    if type(value) is not PilotExactTaskRemotePublicationAuthorization:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "exact remote-publication authorization claim is required"
        )
    replayed = PilotExactTaskRemotePublicationAuthorization.from_mapping(
        value.to_dict()
    )
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization claim replay mismatch"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskRemotePublicationAuthorization
    remote_head_observation_sha256: str
    observation_key_sha256: str
    local_commit_sha: str
    destination_ref: str
    remote_publication_nonce_sha256: str
    verified_at_utc: str
    one_shot_remote_publication_required: bool = True
    fresh_remote_head_revalidation_before_push_required: bool = True
    remote_publication_authorization_consumed: bool = False
    human_remote_publication_authorization_verified: bool = True
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
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof schema unsupported"
            )
        claim = _require_authorization(self.authorization)
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "remote_head_observation_sha256",
            "observation_key_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.local_commit_sha, name="local_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        expected = {
            "authorization_sha256": claim.sha256,
            "remote_head_observation_sha256": claim.remote_head_observation_sha256,
            "observation_key_sha256": claim.observation_key_sha256,
            "local_commit_sha": claim.local_commit_sha,
            "destination_ref": claim.destination_ref,
            "remote_publication_nonce_sha256": claim.remote_publication_nonce_sha256,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                f"authorization proof binding mismatch: {mismatch}"
            )
        if self.issuer_actor_id != claim.remote_publication_authorizer_actor_id:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof issuer actor mismatch"
            )
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof issuer system mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(claim.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(claim.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified >= expires:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "verification time is outside authorization window"
            )
        if (
            self.one_shot_remote_publication_required is not True
            or self.fresh_remote_head_revalidation_before_push_required is not True
            or self.human_remote_publication_authorization_verified is not True
        ):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "verified proof lost required human publication constraints"
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "verified proof cannot grant or consume remote authority"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof authority unsupported"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        result["authorization"] = self.authorization.to_dict()
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationAuthorizationProof":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof fields mismatch"
            )
        mapped = dict(value)
        try:
            mapped["authorization"] = (
                PilotExactTaskRemotePublicationAuthorization.from_mapping(
                    mapped["authorization"]
                )
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "authorization proof nested claim is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_remote_publication_authorization(
    *,
    remote_head_observation: PilotExactTaskRemoteHeadObservation,
    authorization_id: str,
    remote_publication_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    remote_publication_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskRemotePublicationAuthorization:
    observation = _require_live_observation(remote_head_observation)
    return PilotExactTaskRemotePublicationAuthorization(
        authorization_id=authorization_id,
        remote_head_observation=observation,
        remote_head_observation_sha256=observation.sha256,
        observation_key_sha256=observation.observation_key_sha256,
        requirements_sha256=observation.requirements_sha256,
        local_commit_sha=observation.local_commit_sha,
        destination_ref=observation.destination_ref,
        remote_head_present=observation.remote_head_present,
        remote_head_sha=observation.remote_head_sha,
        publication_mode=observation.publication_mode,
        remote_publication_authorizer_actor_id=remote_publication_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        remote_publication_nonce_sha256=remote_publication_nonce_sha256,
        notes=_notes(notes),
    )


def _verify_pilot_exact_task_remote_publication_authorization(
    *,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    claim = _require_authorization(authorization)
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "detached Ed25519 remote-publication signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "Ed25519 remote-publication verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
        or signature.issuer_actor_id
        != claim.remote_publication_authorizer_actor_id
        or signature.signed_at_utc != claim.authorized_at_utc
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication signature identity/time mismatch"
        )
    payload = claim.canonical_json().encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != signature.payload_sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication signature payload mismatch"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(claim.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(claim.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified >= expires:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication authorization is not currently fresh"
        )
    try:
        verifier.verify(
            payload=payload,
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication human signature verification failed"
        ) from exc
    proof = PilotExactTaskRemotePublicationAuthorizationProof(
        authorization_sha256=claim.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=claim,
        remote_head_observation_sha256=claim.remote_head_observation_sha256,
        observation_key_sha256=claim.observation_key_sha256,
        local_commit_sha=claim.local_commit_sha,
        destination_ref=claim.destination_ref,
        remote_publication_nonce_sha256=claim.remote_publication_nonce_sha256,
        verified_at_utc=verified_at,
    )
    replayed = PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
        proof.to_dict()
    )
    if replayed != proof or replayed.sha256 != proof.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "authorization proof replay validation failed"
        )
    return proof


def verify_pilot_exact_task_remote_publication_authorization(
    *,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    raise PilotExactTaskRemotePublicationAuthorizationError(
        "production remote-publication authorization boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PilotExactTaskRemotePublicationAuthorizationError",
    "PilotExactTaskRemotePublicationAuthorization",
    "PilotExactTaskRemotePublicationAuthorizationProof",
    "build_pilot_exact_task_remote_publication_authorization",
    "verify_pilot_exact_task_remote_publication_authorization",
]
