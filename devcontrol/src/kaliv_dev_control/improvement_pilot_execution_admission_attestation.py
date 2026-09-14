"""Public host-pinned verification facade for ADR-DC-028 execution admission."""
from __future__ import annotations

from . import _improvement_pilot_execution_admission_attestation_impl as _implementation
from ._improvement_pilot_execution_admission_attestation_production_boundary import (
    install_pilot_execution_admission_attestation_production_boundary,
)

install_pilot_execution_admission_attestation_production_boundary(_implementation)

PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY
)
PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID
)
RESULT_FIELDS = _implementation.RESULT_FIELDS
PilotExecutionAdmissionAttestationError = (
    _implementation.PilotExecutionAdmissionAttestationError
)
PilotExecutionAdmissionAttestation = _implementation.PilotExecutionAdmissionAttestation
PilotExecutionAdmissionAttestationProof = (
    _implementation.PilotExecutionAdmissionAttestationProof
)
build_pilot_execution_admission_attestation = (
    _implementation.build_pilot_execution_admission_attestation
)
verify_pilot_execution_admission_attestation = (
    _implementation.verify_pilot_execution_admission_attestation
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_execution_admission_attestation = (
    _implementation._verify_pilot_execution_admission_attestation
)

__all__ = [
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID",
    "RESULT_FIELDS",
    "PilotExecutionAdmissionAttestationError",
    "PilotExecutionAdmissionAttestation",
    "PilotExecutionAdmissionAttestationProof",
    "build_pilot_execution_admission_attestation",
    "verify_pilot_execution_admission_attestation",
]

del install_pilot_execution_admission_attestation_production_boundary
