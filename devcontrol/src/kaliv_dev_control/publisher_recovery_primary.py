"""Physically primary authenticated publisher replay recovery ledger (H9).

H9 replaces H7's import-time class mutation with one explicit public ledger
implementation.  The retained H6 ledger remains the fail-closed transition
core; this module adds the consolidated signature-time verifier and canonical
receipt-v3 publication through ordinary inheritance and method dispatch.

No private key, shared secret, credential, Git transport, network client,
repository writer, pull-request writer, merge, release or deployment capability
is accepted or implemented here.
"""
from __future__ import annotations

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    _MAX_ARTIFACT_BYTES,
    _utc,
)
from .durable_publication import DurablePublicationError, create_once_file
from .publisher_authorization_v2 import AsymmetricPublisherAuthorizationLease
from .publisher_recovery_authorization import (
    PublisherReplayLedgerV3 as _H6PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryAuthorizationVerifierV1 as _H6RecoveryVerifier,
    PublisherReplayRecoveryStateV1,
)
from .publisher_recovery_receipt_v3 import (
    PublisherReplayRecoveryReceiptV3,
    load_publisher_replay_recovery_receipt_v3,
)


class PublisherReplayRecoveryAuthorizationVerifierV1(_H6RecoveryVerifier):
    """Single supported verifier with exact signature-window binding."""

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


class PublisherReplayLedgerV3(_H6PublisherReplayLedgerV3):
    """Primary ledger: authenticated transition plus canonical receipt v3."""

    def recover_authenticated(
        self,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        authorization_verifier: PublisherReplayRecoveryAuthorizationVerifierV1,
        recovered_at_utc: str,
    ) -> PublisherReplayRecoveryReceiptV3:
        if not isinstance(
            authorization_verifier,
            PublisherReplayRecoveryAuthorizationVerifierV1,
        ):
            raise PublisherAuthorizationError(
                "recovery requires the consolidated H9 Ed25519 verifier"
            )

        core_receipt = super().recover_authenticated(
            lease=lease,
            authorization=authorization,
            authorization_verifier=authorization_verifier,
            recovered_at_utc=recovered_at_utc,
        )
        receipt = PublisherReplayRecoveryReceiptV3.from_core(
            authorization=authorization,
            core_receipt=core_receipt,
        )
        path = self._root / f"{lease.invocation_nonce}.v3.recovery.json"
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PublisherAuthorizationError(
                "publisher replay recovery receipt v3 exceeds its byte bound"
            )

        if path.exists() or path.is_symlink():
            if (
                path.is_symlink()
                or not path.is_file()
                or path.read_bytes() != payload
            ):
                raise PublisherAuthorizationError(
                    "publisher replay recovery receipt v3 conflicts with durable evidence"
                )
        else:
            try:
                create_once_file(path, payload)
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "publisher replay recovery receipt v3 was not durably published"
                ) from exc

        loaded = load_publisher_replay_recovery_receipt_v3(path)
        if loaded.canonical_json() != receipt.canonical_json():
            raise PublisherAuthorizationError(
                "publisher replay recovery receipt v3 postcondition failed"
            )
        return loaded


__all__ = [
    "PublisherReplayLedgerV3",
    "PublisherReplayRecoveryAuthorizationVerifierV1",
]
