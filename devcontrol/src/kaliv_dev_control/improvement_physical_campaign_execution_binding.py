"""Public exact-runner execution-binding facade for ADR-DC-012.

Production verifies a separately signed human claim using only a host-pinned
public-key keyring. Injectable verifier/clock seams stay private and carry no
production authority.
"""
from __future__ import annotations

from . import _improvement_physical_campaign_execution_binding_impl as _implementation
from ._improvement_physical_campaign_execution_binding_production_boundary import (
    install_physical_campaign_execution_binding_production_boundary,
)

install_physical_campaign_execution_binding_production_boundary(_implementation)

EXECUTION_BINDING_SCHEMA = _implementation.EXECUTION_BINDING_SCHEMA
EXECUTION_PROOF_SCHEMA = _implementation.EXECUTION_PROOF_SCHEMA
EXECUTION_BINDING_CLAIM_AUTHORITY = _implementation.EXECUTION_BINDING_CLAIM_AUTHORITY
EXECUTION_PROOF_AUTHORITY = _implementation.EXECUTION_PROOF_AUTHORITY
EXECUTION_BINDING_ISSUER_SYSTEM_ID = _implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID
REMAINING_COMPLETION_GATES = _implementation.REMAINING_COMPLETION_GATES
PhysicalCampaignExecutionBindingError = _implementation.PhysicalCampaignExecutionBindingError
PhysicalCampaignExecutionBinding = _implementation.PhysicalCampaignExecutionBinding
PhysicalCampaignExecutionProof = _implementation.PhysicalCampaignExecutionProof
build_physical_campaign_execution_binding = _implementation.build_physical_campaign_execution_binding
verify_physical_campaign_execution_binding = _implementation.verify_physical_campaign_execution_binding

# Explicit deterministic test seam; not production authority.
_verify_physical_campaign_execution_binding = _implementation._verify_physical_campaign_execution_binding

__all__ = [
    "EXECUTION_BINDING_SCHEMA",
    "EXECUTION_PROOF_SCHEMA",
    "EXECUTION_BINDING_CLAIM_AUTHORITY",
    "EXECUTION_PROOF_AUTHORITY",
    "EXECUTION_BINDING_ISSUER_SYSTEM_ID",
    "REMAINING_COMPLETION_GATES",
    "PhysicalCampaignExecutionBindingError",
    "PhysicalCampaignExecutionBinding",
    "PhysicalCampaignExecutionProof",
    "build_physical_campaign_execution_binding",
    "verify_physical_campaign_execution_binding",
]

del install_physical_campaign_execution_binding_production_boundary
