"""Public host-pinned facade for ADR-DC-046 local-commit write consumption."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_local_commit_write_consumption_impl as _implementation
from ._improvement_pilot_exact_task_local_commit_write_consumption_production_boundary import (
    install_pilot_exact_task_local_commit_write_consumption_production_boundary,
)

install_pilot_exact_task_local_commit_write_consumption_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE
)
PilotExactTaskLocalCommitWriteConsumptionError = (
    _implementation.PilotExactTaskLocalCommitWriteConsumptionError
)
PilotExactTaskLocalCommitWriteConsumptionReceipt = (
    _implementation.PilotExactTaskLocalCommitWriteConsumptionReceipt
)
consume_pilot_exact_task_local_commit_authorization = (
    _implementation.consume_pilot_exact_task_local_commit_authorization
)

# Deterministic support seams only. Production consumption is host-pinned above.
_PilotExactTaskLocalCommitWriteConsumptionLedger = (
    _implementation._PilotExactTaskLocalCommitWriteConsumptionLedger
)
_consume_verified_pilot_exact_task_local_commit_authorization = (
    _implementation._consume_verified_pilot_exact_task_local_commit_authorization
)
_get_live_local_commit_write_consumption_inputs = (
    _implementation._get_live_local_commit_write_consumption_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitWriteConsumptionError",
    "PilotExactTaskLocalCommitWriteConsumptionReceipt",
    "consume_pilot_exact_task_local_commit_authorization",
]

del install_pilot_exact_task_local_commit_write_consumption_production_boundary
