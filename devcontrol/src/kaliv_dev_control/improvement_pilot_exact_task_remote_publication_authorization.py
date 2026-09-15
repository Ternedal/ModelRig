"""Public host-pinned facade for ADR-DC-051 exact remote-publication human authority."""
from __future__ import annotations

from typing import Sequence

from . import _improvement_pilot_exact_task_remote_publication_authorization_impl as _implementation
from ._improvement_pilot_exact_task_remote_publication_authorization_production_boundary import (
    install_pilot_exact_task_remote_publication_authorization_production_boundary,
)
from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_exact_task_remote_head_observation import (
    PilotExactTaskRemoteHeadObservation,
)

install_pilot_exact_task_remote_publication_authorization_production_boundary(_implementation)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PilotExactTaskRemotePublicationAuthorizationError = (
    _implementation.PilotExactTaskRemotePublicationAuthorizationError
)
PilotExactTaskRemotePublicationAuthorization = (
    _implementation.PilotExactTaskRemotePublicationAuthorization
)
PilotExactTaskRemotePublicationAuthorizationProof = (
    _implementation.PilotExactTaskRemotePublicationAuthorizationProof
)


def _enforce_remote_publication_claim_policy(
    authorization: PilotExactTaskRemotePublicationAuthorization,
) -> PilotExactTaskRemotePublicationAuthorization:
    claim = _implementation._require_authorization(authorization)
    observed = _implementation._utc(
        claim.remote_head_observation.observation_completed_at_utc,
        name="observation_completed_at_utc",
    )
    authorized = _implementation._utc(
        claim.authorized_at_utc,
        name="authorized_at_utc",
    )
    if (
        authorized - observed
    ).total_seconds() > _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "human authorization is too far removed from the remote-head observation"
        )
    prior_local_commit_nonce = (
        claim.remote_head_observation.requirements.local_commit_nonce_sha256
    )
    if claim.remote_publication_nonce_sha256 == prior_local_commit_nonce:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote-publication nonce must differ from the prior local-commit nonce"
        )
    return claim


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
    claim = _implementation.build_pilot_exact_task_remote_publication_authorization(
        remote_head_observation=remote_head_observation,
        authorization_id=authorization_id,
        remote_publication_authorizer_actor_id=remote_publication_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        remote_publication_nonce_sha256=remote_publication_nonce_sha256,
        notes=notes,
    )
    return _enforce_remote_publication_claim_policy(claim)


def verify_pilot_exact_task_remote_publication_authorization(
    *,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    claim = _enforce_remote_publication_claim_policy(authorization)
    return _implementation.verify_pilot_exact_task_remote_publication_authorization(
        authorization=claim,
        signature=signature,
    )


# Deterministic test seam only; production verification remains host-pinned above.
def _verify_pilot_exact_task_remote_publication_authorization(
    *,
    authorization: PilotExactTaskRemotePublicationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    claim = _enforce_remote_publication_claim_policy(authorization)
    return _implementation._verify_pilot_exact_task_remote_publication_authorization(
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=now_provider,
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

del install_pilot_exact_task_remote_publication_authorization_production_boundary
