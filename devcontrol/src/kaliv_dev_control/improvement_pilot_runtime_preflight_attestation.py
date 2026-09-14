"""Public host-pinned verification facade for ADR-DC-022 runtime preflight."""
from __future__ import annotations

from . import _improvement_pilot_runtime_preflight_attestation_impl as _implementation
from ._improvement_pilot_runtime_preflight_attestation_production_boundary import (
    install_pilot_runtime_preflight_production_boundary,
)

install_pilot_runtime_preflight_production_boundary(_implementation)

PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA
)
PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA = _implementation.PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA
PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
)
PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY
)
PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID
)
PilotRuntimePreflightError = _implementation.PilotRuntimePreflightError
PilotRuntimePreflightObservation = _implementation.PilotRuntimePreflightObservation
PilotRuntimePreflightProof = _implementation.PilotRuntimePreflightProof
build_pilot_runtime_preflight_observation = (
    _implementation.build_pilot_runtime_preflight_observation
)
verify_pilot_runtime_preflight = _implementation.verify_pilot_runtime_preflight

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_runtime_preflight = _implementation._verify_pilot_runtime_preflight

__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID",
    "PilotRuntimePreflightError",
    "PilotRuntimePreflightObservation",
    "PilotRuntimePreflightProof",
    "build_pilot_runtime_preflight_observation",
    "verify_pilot_runtime_preflight",
]

del install_pilot_runtime_preflight_production_boundary
