"""Public host-pinned facade for ADR-DC-045 exact local-write reservation."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_local_commit_write_reservation_impl as _implementation
from ._improvement_pilot_exact_task_local_commit_write_reservation_production_boundary import (
    install_pilot_exact_task_local_commit_write_reservation_production_boundary,
)

install_pilot_exact_task_local_commit_write_reservation_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE
)
PilotExactTaskLocalCommitWriteReservationError = (
    _implementation.PilotExactTaskLocalCommitWriteReservationError
)
PilotExactTaskLocalCommitWriteReservationReceipt = (
    _implementation.PilotExactTaskLocalCommitWriteReservationReceipt
)
reserve_pilot_exact_task_local_commit_write = (
    _implementation.reserve_pilot_exact_task_local_commit_write
)

# Deterministic support seams only; production reservation is host-pinned above.
_require_authorization_proof = _implementation._require_authorization_proof
require_fresh_authorization_proof_identity = (
    _implementation.require_fresh_authorization_proof_identity
)
_require_live_identity = _implementation._require_live_identity
_require_proof_identity_binding = _implementation._require_proof_identity_binding
_fresh_identity_revalidation = _implementation._fresh_identity_revalidation
_PilotExactTaskLocalCommitWriteReservationLedger = (
    _implementation._PilotExactTaskLocalCommitWriteReservationLedger
)
_reserve_verified_exact_task_local_commit_write = (
    _implementation._reserve_verified_exact_task_local_commit_write
)
_get_live_local_commit_write_reservation_inputs = (
    _implementation._get_live_local_commit_write_reservation_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitWriteReservationError",
    "PilotExactTaskLocalCommitWriteReservationReceipt",
    "reserve_pilot_exact_task_local_commit_write",
]

del install_pilot_exact_task_local_commit_write_reservation_production_boundary
