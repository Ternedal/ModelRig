"""Strict public H6 recovery verifier with signature-time binding."""
from __future__ import annotations

from ._publisher_authorization_legacy import PublisherAuthorizationError, _utc
from .publisher_recovery_authorization import (
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryAuthorizationVerifierV1 as _BaseRecoveryVerifier,
    PublisherReplayRecoveryStateV1,
)
from .publisher_authorization_v2 import AsymmetricPublisherAuthorizationLease


class PublisherReplayRecoveryAuthorizationVerifierV1(_BaseRecoveryVerifier):
    """Require both signatures to be made inside the exact approval window."""

    def verify(
        self,
        *,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        lease: AsymmetricPublisherAuthorizationLease,
        current_state: PublisherReplayRecoveryStateV1,
        at_utc: str,
    ) -> PublisherReplayRecoveryAuthorizationV1:
        verified = super().verify(
            authorization=authorization,
            lease=lease,
            current_state=current_state,
            at_utc=at_utc,
        )
        requested = _utc(
            authorization.requested_at_utc,
            name="recovery request time",
        )
        expires = _utc(
            authorization.expires_at_utc,
            name="recovery authorization expiry",
        )
        for signature, role in (
            (authorization.operator_signature, "operator"),
            (authorization.reviewer_signature, "reviewer"),
        ):
            signed = _utc(
                signature.signed_at_utc,
                name=f"recovery {role} signature time",
            )
            if signed < requested or signed >= expires:
                raise PublisherAuthorizationError(
                    f"recovery {role} signature is outside the approval window"
                )
        return verified


__all__ = ["PublisherReplayRecoveryAuthorizationVerifierV1"]
