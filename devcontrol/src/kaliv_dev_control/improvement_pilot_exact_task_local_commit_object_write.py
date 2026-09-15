"""Public host-pinned facade for ADR-DC-047 exact local Git object materialization."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_local_commit_object_write_impl as _implementation
from ._improvement_pilot_exact_task_local_commit_object_write_production_boundary import (
    install_pilot_exact_task_local_commit_object_write_production_boundary,
)

install_pilot_exact_task_local_commit_object_write_production_boundary(_implementation)

PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE
)
PilotExactTaskLocalCommitObjectWriteError = (
    _implementation.PilotExactTaskLocalCommitObjectWriteError
)
PilotExactTaskLocalCommitObjectWriteReceipt = (
    _implementation.PilotExactTaskLocalCommitObjectWriteReceipt
)
materialize_pilot_exact_task_local_commit_objects = (
    _implementation.materialize_pilot_exact_task_local_commit_objects
)

# Deterministic support seams only. Production object writes are host-pinned above.
_tree_object_plan = _implementation._tree_object_plan
_hash_object_write = _implementation._hash_object_write
_PilotExactTaskLocalCommitObjectWriteLedger = (
    _implementation._PilotExactTaskLocalCommitObjectWriteLedger
)
_materialize_verified_pilot_exact_task_local_commit_objects = (
    _implementation._materialize_verified_pilot_exact_task_local_commit_objects
)
_get_live_local_commit_object_write_inputs = (
    _implementation._get_live_local_commit_object_write_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitObjectWriteError",
    "PilotExactTaskLocalCommitObjectWriteReceipt",
    "materialize_pilot_exact_task_local_commit_objects",
]

del install_pilot_exact_task_local_commit_object_write_production_boundary
