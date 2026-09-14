"""Public host-pinned facade for ADR-DC-029 exact task execution admission."""
from __future__ import annotations

from . import _improvement_pilot_task_execution_admission_impl as _implementation
from ._improvement_pilot_task_execution_admission_production_boundary import (
    install_pilot_task_execution_admission_production_boundary,
)

install_pilot_task_execution_admission_production_boundary(_implementation)

PILOT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA = (
    _implementation.PILOT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
)
PILOT_TASK_EXECUTION_ADMISSION_AUTHORITY = (
    _implementation.PILOT_TASK_EXECUTION_ADMISSION_AUTHORITY
)
PILOT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE = (
    _implementation.PILOT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
)
PILOT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS = (
    _implementation.PILOT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS
)
PilotTaskExecutionAdmissionError = _implementation.PilotTaskExecutionAdmissionError
PilotTaskExecutionAdmissionReceipt = _implementation.PilotTaskExecutionAdmissionReceipt
admit_pilot_task_execution = _implementation.admit_pilot_task_execution

# Deterministic test seams only. Production callers use the host-pinned function above.
_PilotTaskExecutionAdmissionLedger = _implementation._PilotTaskExecutionAdmissionLedger
_admit_verified_pilot_task_execution = (
    _implementation._admit_verified_pilot_task_execution
)
require_fresh_proof_identity = _implementation.require_fresh_proof_identity

__all__ = [
    "PILOT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA",
    "PILOT_TASK_EXECUTION_ADMISSION_AUTHORITY",
    "PILOT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE",
    "PILOT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS",
    "PilotTaskExecutionAdmissionError",
    "PilotTaskExecutionAdmissionReceipt",
    "admit_pilot_task_execution",
]

del install_pilot_task_execution_admission_production_boundary
