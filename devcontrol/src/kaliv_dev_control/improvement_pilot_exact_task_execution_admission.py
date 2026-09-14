"""Public host-pinned facade for ADR-DC-033 exact-task execution admission."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_execution_admission_impl as _implementation
from ._improvement_pilot_exact_task_execution_admission_production_boundary import (
    install_pilot_exact_task_execution_admission_production_boundary,
)

install_pilot_exact_task_execution_admission_production_boundary(_implementation)

PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS
)
PilotExactTaskExecutionAdmissionError = (
    _implementation.PilotExactTaskExecutionAdmissionError
)
PilotExactTaskExecutionAdmissionReceipt = (
    _implementation.PilotExactTaskExecutionAdmissionReceipt
)
admit_pilot_exact_task_execution = _implementation.admit_pilot_exact_task_execution

# Deterministic support seams only. Production admission is host-pinned above.
_require_satisfied_revalidation_proof = _implementation._require_satisfied_revalidation_proof
require_fresh_revalidation_proof_identity = (
    _implementation.require_fresh_revalidation_proof_identity
)
_admission_key = _implementation._admission_key
_scope = _implementation._scope
_PilotExactTaskExecutionAdmissionLedger = (
    _implementation._PilotExactTaskExecutionAdmissionLedger
)
_admit_verified_exact_task_execution = (
    _implementation._admit_verified_exact_task_execution
)

__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS",
    "PilotExactTaskExecutionAdmissionError",
    "PilotExactTaskExecutionAdmissionReceipt",
    "admit_pilot_exact_task_execution",
]

del install_pilot_exact_task_execution_admission_production_boundary
