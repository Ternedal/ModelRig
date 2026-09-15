"""Public host-pinned facade for ADR-DC-048 exact local branch ref update."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_local_commit_ref_update_impl as _implementation
from ._improvement_pilot_exact_task_local_commit_ref_update_production_boundary import (
    install_pilot_exact_task_local_commit_ref_update_production_boundary,
)

install_pilot_exact_task_local_commit_ref_update_production_boundary(_implementation)

PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE
)
PilotExactTaskLocalCommitRefUpdateError = (
    _implementation.PilotExactTaskLocalCommitRefUpdateError
)
PilotExactTaskLocalCommitRefUpdateReceipt = (
    _implementation.PilotExactTaskLocalCommitRefUpdateReceipt
)
attach_pilot_exact_task_local_commit = (
    _implementation.attach_pilot_exact_task_local_commit
)

# Deterministic support seams only. Production ref updates are host-pinned above.
_PilotExactTaskLocalCommitRefUpdateLedger = (
    _implementation._PilotExactTaskLocalCommitRefUpdateLedger
)
_attach_verified_pilot_exact_task_local_commit = (
    _implementation._attach_verified_pilot_exact_task_local_commit
)
_get_live_local_commit_ref_update_inputs = (
    _implementation._get_live_local_commit_ref_update_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitRefUpdateError",
    "PilotExactTaskLocalCommitRefUpdateReceipt",
    "attach_pilot_exact_task_local_commit",
]

del install_pilot_exact_task_local_commit_ref_update_production_boundary
