"""Authenticated finalization of a missing publisher recovery receipt v3 (H8).

This module addresses only the narrow crash window where the authenticated H6
recovery transition and its durable v2 evidence completed, but H7 receipt-v3
publication did not.  The finalizer loads all authority and transition evidence
from fixed ledger paths, verifies the original dual Ed25519 authorization at
the recorded recovery time, verifies the exact current durable post-state, and
publishes only the missing deterministic receipt v3.

It never calls a recovery transition, changes nonce state, accepts a private
key or credential, configures a remote, performs network I/O, writes GitHub, or
provides merge, release or deployment authority.
"""
from __future__ import annotations

from datetime import datetime

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    _utc,
)
from .publisher_authorization_chain_v2 import (
    PublisherReplayRecoveryReceiptV2,
    load_publisher_replay_recovery_receipt_v2,
)
from .publisher_authorization_v2 import AsymmetricPublisherAuthorizationLease
from .publisher_recovery_authorization import (
    PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryStateV1,
    load_publisher_replay_recovery_authorization_v1,
)
from .publisher_recovery_receipt_v3 import (
    PublisherReplayRecoveryAuthorizationVerifierV1,
    PublisherReplayRecoveryReceiptV3,
    load_publisher_replay_recovery_receipt_v3,
    write_publisher_replay_recovery_receipt_v3,
)


def _state_fingerprint(state: PublisherReplayRecoveryStateV1) -> tuple[object, ...]:
    """Return every durable-state field except the caller supplied observation time."""

    if not isinstance(state, PublisherReplayRecoveryStateV1):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization state is invalid"
        )
    return (
        state.lease_sha256,
        state.invocation_nonce,
        state.ledger_id,
        state.state,
        state.final_present,
        state.final_sha256,
        state.pending_present,
        state.pending_sha256,
        state.reservation_present,
        state.reservation_sha256,
        state.recovery_present,
        state.recovery_sha256,
    )


def _verify_exact_post_state(
    *,
    ledger: PublisherReplayLedgerV3,
    lease: AsymmetricPublisherAuthorizationLease,
    authorization: PublisherReplayRecoveryAuthorizationV1,
    core_receipt: PublisherReplayRecoveryReceiptV2,
    state: PublisherReplayRecoveryStateV1,
) -> None:
    """Verify the complete clean topology expected after the recorded transition."""

    if (
        state.lease_sha256 != lease.sha256
        or state.invocation_nonce != lease.invocation_nonce
        or state.ledger_id != ledger._ledger_id
        or state.state != core_receipt.state_after
        or not state.recovery_present
        or state.recovery_sha256 != core_receipt.sha256
        or state.pending_present
        or state.reservation_present
    ):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization durable post-state is inconsistent"
        )

    signed_state = authorization.state
    if signed_state.recovery_present:
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization requires a pre-transition authorization"
        )

    final_path, _, _, _ = ledger._paths(lease.invocation_nonce)
    if core_receipt.action == "finalize_prepared":
        expected_final = signed_state.pending_sha256
        if (
            signed_state.state != "prepared"
            or not signed_state.pending_present
            or expected_final is None
            or not state.final_present
            or state.final_sha256 != expected_final
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 finalization prepared transition is inconsistent"
            )
        ledger._entry(final_path).verify_against(lease)
    elif core_receipt.action == "acknowledge_committed":
        expected_final = signed_state.final_sha256
        if (
            signed_state.state not in {"committed", "committed_locked"}
            or not signed_state.final_present
            or expected_final is None
            or not state.final_present
            or state.final_sha256 != expected_final
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 finalization committed transition is inconsistent"
            )
        ledger._entry(final_path).verify_against(lease)
    elif core_receipt.action == "tombstone_uncertain":
        if (
            signed_state.state not in {"reserved", "partial"}
            or state.final_present
            or state.state != "tombstoned"
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 finalization tombstone transition is inconsistent"
            )
    else:
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization action is unsupported"
        )


def finalize_missing_publisher_replay_recovery_receipt_v3(
    *,
    ledger: PublisherReplayLedgerV3,
    lease: AsymmetricPublisherAuthorizationLease,
    authorization_verifier: PublisherReplayRecoveryAuthorizationVerifierV1,
    finalized_at_utc: str,
) -> PublisherReplayRecoveryReceiptV3:
    """Publish only a missing v3 receipt for an already completed recovery.

    The function deliberately accepts neither authorization nor core receipt
    objects from the caller.  Both are loaded canonically from the exact ledger
    paths.  The original transition is never called or repeated.
    """

    if not isinstance(ledger, PublisherReplayLedgerV3):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization ledger is invalid"
        )
    if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization lease is invalid"
        )
    if not isinstance(
        authorization_verifier,
        PublisherReplayRecoveryAuthorizationVerifierV1,
    ):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization requires the consolidated verifier"
        )

    finalized: datetime = _utc(
        finalized_at_utc,
        name="recovery receipt v3 finalization time",
    )
    nonce = lease.invocation_nonce
    _, _, _, core_path = ledger._paths(nonce)
    authorization_path = (
        ledger._root / f"{nonce}.v2.recovery-authorization.json"
    )
    receipt_v3_path = ledger._root / f"{nonce}.v3.recovery.json"

    if receipt_v3_path.exists() or receipt_v3_path.is_symlink():
        raise PublisherAuthorizationError(
            "recovery receipt v3 already exists; finalization is not replayable"
        )

    authorization = load_publisher_replay_recovery_authorization_v1(
        authorization_path
    )
    core_receipt = load_publisher_replay_recovery_receipt_v2(core_path)

    if (
        authorization.state.lease_sha256 != lease.sha256
        or authorization.state.invocation_nonce != nonce
        or authorization.state.ledger_id != ledger._ledger_id
        or core_receipt.lease_sha256 != lease.sha256
        or core_receipt.invocation_nonce != nonce
        or core_receipt.ledger_id != ledger._ledger_id
        or core_receipt.recovery_authorization_sha256 != authorization.sha256
    ):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization evidence belongs to another authority chain"
        )

    recovered = _utc(
        core_receipt.recovered_at_utc,
        name="recovery receipt v3 recorded recovery time",
    )
    if finalized < recovered:
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization predates the recovery transition"
        )

    # Verify the original authorization at the time it authorized the already
    # completed transition. Finalization itself may occur after its expiry.
    authorization_verifier.verify(
        authorization=authorization,
        lease=lease,
        current_state=authorization.state,
        at_utc=core_receipt.recovered_at_utc,
    )

    before_publication = ledger.observe_recovery_state(
        lease=lease,
        observed_at_utc=finalized_at_utc,
    )
    _verify_exact_post_state(
        ledger=ledger,
        lease=lease,
        authorization=authorization,
        core_receipt=core_receipt,
        state=before_publication,
    )

    receipt = PublisherReplayRecoveryReceiptV3.from_core(
        authorization=authorization,
        core_receipt=core_receipt,
    )
    write_publisher_replay_recovery_receipt_v3(receipt_v3_path, receipt)

    after_publication = ledger.observe_recovery_state(
        lease=lease,
        observed_at_utc=finalized_at_utc,
    )
    if _state_fingerprint(after_publication) != _state_fingerprint(
        before_publication
    ):
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization changed durable nonce state"
        )
    _verify_exact_post_state(
        ledger=ledger,
        lease=lease,
        authorization=authorization,
        core_receipt=core_receipt,
        state=after_publication,
    )

    loaded = load_publisher_replay_recovery_receipt_v3(receipt_v3_path)
    if loaded.canonical_json() != receipt.canonical_json():
        raise PublisherAuthorizationError(
            "recovery receipt v3 finalization postcondition failed"
        )
    return loaded


__all__ = [
    "finalize_missing_publisher_replay_recovery_receipt_v3",
]
