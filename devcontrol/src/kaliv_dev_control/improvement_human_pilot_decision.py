"""Public verification facade for ADR-DC-015 human pilot GO/NO-GO decisions."""
from __future__ import annotations

from . import _improvement_human_pilot_decision_impl as _implementation
from ._improvement_human_pilot_decision_production_boundary import (
    install_human_pilot_decision_production_boundary,
)

install_human_pilot_decision_production_boundary(_implementation)

HUMAN_PILOT_DECISION_SCHEMA = _implementation.HUMAN_PILOT_DECISION_SCHEMA
HUMAN_PILOT_DECISION_PROOF_SCHEMA = _implementation.HUMAN_PILOT_DECISION_PROOF_SCHEMA
HUMAN_PILOT_DECISION_AUTHORITY = _implementation.HUMAN_PILOT_DECISION_AUTHORITY
HUMAN_PILOT_DECISION_PROOF_AUTHORITY = _implementation.HUMAN_PILOT_DECISION_PROOF_AUTHORITY
HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID = _implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID
HumanPilotDecisionError = _implementation.HumanPilotDecisionError
HumanPilotDecision = _implementation.HumanPilotDecision
HumanPilotDecisionProof = _implementation.HumanPilotDecisionProof
build_human_pilot_decision = _implementation.build_human_pilot_decision
verify_human_pilot_decision = _implementation.verify_human_pilot_decision

# Explicit deterministic test seam; not production authority.
_verify_human_pilot_decision = _implementation._verify_human_pilot_decision

__all__ = [
    "HUMAN_PILOT_DECISION_SCHEMA",
    "HUMAN_PILOT_DECISION_PROOF_SCHEMA",
    "HUMAN_PILOT_DECISION_AUTHORITY",
    "HUMAN_PILOT_DECISION_PROOF_AUTHORITY",
    "HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID",
    "HumanPilotDecisionError",
    "HumanPilotDecision",
    "HumanPilotDecisionProof",
    "build_human_pilot_decision",
    "verify_human_pilot_decision",
]

del install_human_pilot_decision_production_boundary
