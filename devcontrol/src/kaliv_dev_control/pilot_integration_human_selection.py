"""Public host-pinned verification facade for ADR-DC-021 human selection."""
from __future__ import annotations

from . import improvement_pilot_integration_human_selection as _implementation
from ._improvement_pilot_integration_human_selection_production_boundary import (
    install_pilot_integration_human_selection_production_boundary,
)

install_pilot_integration_human_selection_production_boundary(_implementation)

PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA
)
PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA
)
PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY
)
PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY
)
PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID
)
PILOT_INTEGRATION_HUMAN_SELECTION_INTENT = (
    _implementation.PILOT_INTEGRATION_HUMAN_SELECTION_INTENT
)
PilotIntegrationHumanSelectionError = (
    _implementation.PilotIntegrationHumanSelectionError
)
PilotIntegrationHumanSelection = _implementation.PilotIntegrationHumanSelection
PilotIntegrationHumanSelectionProof = (
    _implementation.PilotIntegrationHumanSelectionProof
)
build_pilot_integration_human_selection = (
    _implementation.build_pilot_integration_human_selection
)
verify_pilot_integration_human_selection = (
    _implementation.verify_pilot_integration_human_selection
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_integration_human_selection = (
    _implementation._verify_pilot_integration_human_selection
)

__all__ = [
    "PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA",
    "PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA",
    "PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY",
    "PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY",
    "PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID",
    "PILOT_INTEGRATION_HUMAN_SELECTION_INTENT",
    "PilotIntegrationHumanSelectionError",
    "PilotIntegrationHumanSelection",
    "PilotIntegrationHumanSelectionProof",
    "build_pilot_integration_human_selection",
    "verify_pilot_integration_human_selection",
]

del install_pilot_integration_human_selection_production_boundary
