"""Public host-pinned facade for ADR-DC-032 exact-task revalidation attestation."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_execution_revalidation_attestation_impl as _implementation
from ._improvement_pilot_exact_task_execution_revalidation_attestation_production_boundary import (
    install_pilot_exact_task_execution_revalidation_attestation_production_boundary,
)

install_pilot_exact_task_execution_revalidation_attestation_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
)
RESULT_FIELDS = _implementation.RESULT_FIELDS
PilotExactTaskExecutionRevalidationAttestationError = (
    _implementation.PilotExactTaskExecutionRevalidationAttestationError
)
PilotExactTaskExecutionRevalidationAttestation = (
    _implementation.PilotExactTaskExecutionRevalidationAttestation
)
PilotExactTaskExecutionRevalidationAttestationProof = (
    _implementation.PilotExactTaskExecutionRevalidationAttestationProof
)
build_pilot_exact_task_execution_revalidation_attestation = (
    _implementation.build_pilot_exact_task_execution_revalidation_attestation
)
verify_pilot_exact_task_execution_revalidation_attestation = (
    _implementation.verify_pilot_exact_task_execution_revalidation_attestation
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_exact_task_execution_revalidation_attestation = (
    _implementation._verify_pilot_exact_task_execution_revalidation_attestation
)

__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID",
    "RESULT_FIELDS",
    "PilotExactTaskExecutionRevalidationAttestationError",
    "PilotExactTaskExecutionRevalidationAttestation",
    "PilotExactTaskExecutionRevalidationAttestationProof",
    "build_pilot_exact_task_execution_revalidation_attestation",
    "verify_pilot_exact_task_execution_revalidation_attestation",
]

del install_pilot_exact_task_execution_revalidation_attestation_production_boundary
