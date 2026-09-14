"""Public host-pinned verification facade for ADR-DC-023 runtime preflight."""
from __future__ import annotations

from . import _improvement_pilot_runtime_preflight_attestation_impl as _implementation
from ._improvement_pilot_runtime_preflight_attestation_production_boundary import (
    install_pilot_runtime_preflight_attestation_production_boundary,
)

install_pilot_runtime_preflight_attestation_production_boundary(_implementation)

PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
)
PilotRuntimePreflightAttestationError = (
    _implementation.PilotRuntimePreflightAttestationError
)
PilotRuntimePreflightAttestation = _implementation.PilotRuntimePreflightAttestation
PilotRuntimePreflightAttestationProof = (
    _implementation.PilotRuntimePreflightAttestationProof
)
build_pilot_runtime_preflight_attestation = (
    _implementation.build_pilot_runtime_preflight_attestation
)
verify_pilot_runtime_preflight_attestation = (
    _implementation.verify_pilot_runtime_preflight_attestation
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_runtime_preflight_attestation = (
    _implementation._verify_pilot_runtime_preflight_attestation
)

__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID",
    "PilotRuntimePreflightAttestationError",
    "PilotRuntimePreflightAttestation",
    "PilotRuntimePreflightAttestationProof",
    "build_pilot_runtime_preflight_attestation",
    "verify_pilot_runtime_preflight_attestation",
]

del install_pilot_runtime_preflight_attestation_production_boundary
