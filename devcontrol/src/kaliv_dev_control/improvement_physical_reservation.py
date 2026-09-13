"""Public RSI physical-request reservation authority facade.

The public consume path deliberately does not accept an Ed25519 verifier or
keyring from its caller. Production verification resolves the pinned public
trust root from the fixed host-controlled authority keyring. The durable replay
ledger is likewise resolved only from a fixed administrator-controlled path;
the injectable transaction implementation remains private for deterministic
adversarial tests.
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
from ._improvement_physical_reservation_directory_provenance import (
    install_directory_history_provenance,
)
from ._improvement_physical_reservation_directory_arming import (
    install_directory_history_arming_guard,
)
from ._improvement_physical_runtime_host_control import (
    PhysicalHostRuntimeError,
    install_host_controlled_physical_runtime_boundary,
)
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _canonical_host_controlled_ledger_root,
)
from . import _improvement_physical_reservation_impl as _implementation

# Install original-file provenance first, then directory-history provenance and
# the Linux watch-before-trust arming guard. Production Git execution is finally
# narrowed to an administrator-controlled runtime tree before exposing authority.
install_descriptor_bound_provenance(_implementation)
install_directory_history_provenance(_implementation)
install_directory_history_arming_guard()
install_host_controlled_physical_runtime_boundary(_implementation)
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
_consume_physical_qualification_request_once_host_controlled = (
    _implementation._consume_physical_qualification_request_once_host_controlled
)
_observe_with_reader = _implementation._observe_with_reader
_canonical = _implementation._canonical
# Public production replay state must come from the privilege-separated resolver,
# never the generic link-free directory creator retained by the private test seam.
_canonical_host_ledger_root = _canonical_host_controlled_ledger_root
_canonical_host_state_root = _implementation._canonical_host_state_root
_canonical_repository_root = _implementation._canonical_repository_root
_canonical_operation_root = _implementation._canonical_operation_root
_ensure_link_free_directory = _implementation._ensure_link_free_directory
_path_sha256 = _implementation._path_sha256
_read_bound_file = _implementation._read_bound_file
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

    Callers cannot select the verification trust root or replay ledger. The
    pinned Ed25519 public keyring and permanent replay state are resolved from
    fixed host-admin-controlled locations; missing or unsafe host state fails
    closed. Production Git observations likewise execute only from an
    administrator-controlled runtime tree. Callers also cannot supply repository
    root, operation root, observation evidence, clock, ledger ID/root, or a
    prebuilt receipt.
    """

    try:
        verifier = _canonical_physical_request_authority_verifier()
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalQualificationReservationError(
            "host-controlled physical request authority keyring is unavailable"
        ) from exc
    try:
        ledger_root = _canonical_host_ledger_root()
    except PhysicalHostStateError as exc:
        raise PhysicalQualificationReservationError(
            "host-controlled physical request replay ledger is unavailable"
        ) from exc
    try:
        return _consume_physical_qualification_request_once_host_controlled(
            ledger_root=ledger_root,
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
    except PhysicalHostRuntimeError as exc:
        raise PhysicalQualificationReservationError(
            "host-controlled physical request Git runtime is unavailable"
        ) from exc


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
