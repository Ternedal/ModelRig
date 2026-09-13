"""Public RSI physical-request reservation authority facade.

The public consume path deliberately does not accept an Ed25519 verifier or
keyring from its caller. Production verification resolves the pinned public
trust root from the fixed host-controlled authority keyring. The injectable
transaction implementation remains private for deterministic adversarial tests.
"""
from __future__ import annotations

from .asymmetric_authority import DetachedEd25519AuthoritySignature
from .improvement_candidate_snapshot import CandidateSnapshotReceipt
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _canonical_physical_request_authority_verifier,
)
from .improvement_physical_request import PhysicalQualificationRequest
from .improvement_qualification_packet import QualificationPacket
from .trusted_git_runtime_staging import TrustedGitRuntime
from ._improvement_physical_reservation_provenance import (
    install_descriptor_bound_provenance,
)
from . import _improvement_physical_reservation_impl as _implementation

# Install descriptor/file-identity provenance before any production transaction.
install_descriptor_bound_provenance(_implementation)
# The old convenience wrapper accepted a caller-selected verifier. The loaded
# implementation retains only the explicitly private injectable transaction.
if hasattr(_implementation, "consume_physical_qualification_request_once"):
    delattr(_implementation, "consume_physical_qualification_request_once")

MAIN_OBSERVATION_SCHEMA = _implementation.MAIN_OBSERVATION_SCHEMA
RESERVATION_SCHEMA = _implementation.RESERVATION_SCHEMA
RESERVATION_AUTHORITY = _implementation.RESERVATION_AUTHORITY
LEDGER_SCOPE = _implementation.LEDGER_SCOPE
MAIN_REF = _implementation.MAIN_REF
PhysicalQualificationReservationError = _implementation.PhysicalQualificationReservationError
LocalMainHeadObservation = _implementation.LocalMainHeadObservation
PhysicalQualificationReservation = _implementation.PhysicalQualificationReservation
observe_local_main_head = _implementation.observe_local_main_head
_PhysicalQualificationRequestLedger = _implementation._PhysicalQualificationRequestLedger
_consume_physical_qualification_request_once = (
    _implementation._consume_physical_qualification_request_once
)
_observe_with_reader = _implementation._observe_with_reader
_canonical = _implementation._canonical
_canonical_host_ledger_root = _implementation._canonical_host_ledger_root
_canonical_repository_root = _implementation._canonical_repository_root
_canonical_operation_root = _implementation._canonical_operation_root
_now_utc_seconds = _implementation._now_utc_seconds

del _implementation


def consume_physical_qualification_request_once(
    *,
    trusted_git: TrustedGitRuntime,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
) -> PhysicalQualificationReservation:
    """Authenticate, observe, and host-reserve one request exactly once.

    Callers cannot select the verification trust root. The pinned Ed25519 public
    keyring is resolved from fixed host-controlled authority state; a missing or
    invalid host trust root fails closed. Callers also cannot supply repository
    root, operation root, observation evidence, clock, ledger ID/root, or a
    prebuilt receipt.
    """

    try:
        verifier = _canonical_physical_request_authority_verifier()
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalQualificationReservationError(
            "host-controlled physical request authority keyring is unavailable"
        ) from exc
    return _consume_physical_qualification_request_once(
        ledger_root=_canonical_host_ledger_root(),
        trusted_git=trusted_git,
        repository_root=_canonical_repository_root(),
        operation_root=_canonical_operation_root(),
        request=request,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "MAIN_OBSERVATION_SCHEMA",
    "RESERVATION_SCHEMA",
    "RESERVATION_AUTHORITY",
    "LEDGER_SCOPE",
    "MAIN_REF",
    "PhysicalQualificationReservationError",
    "LocalMainHeadObservation",
    "PhysicalQualificationReservation",
    "observe_local_main_head",
    "consume_physical_qualification_request_once",
]
