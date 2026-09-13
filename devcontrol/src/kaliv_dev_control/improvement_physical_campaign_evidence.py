"""Public post-DC-L15 physical-evidence facade.

Production callers receive only the host-pinned facade installed below.  The
injectable implementation lives in the underscored module solely for deterministic
adversarial tests and is not production authority.
"""
from __future__ import annotations

from . import _improvement_physical_campaign_evidence_impl as _implementation
from ._improvement_physical_campaign_evidence_production_boundary import (
    install_physical_campaign_evidence_production_boundary,
)

install_physical_campaign_evidence_production_boundary(_implementation)

EVIDENCE_SNAPSHOT_SCHEMA = _implementation.EVIDENCE_SNAPSHOT_SCHEMA
EVIDENCE_SNAPSHOT_AUTHORITY = _implementation.EVIDENCE_SNAPSHOT_AUTHORITY
MISSING_COMPLETION_GATES = _implementation.MISSING_COMPLETION_GATES
PhysicalCampaignEvidenceError = _implementation.PhysicalCampaignEvidenceError
PhysicalCampaignEvidenceSnapshot = _implementation.PhysicalCampaignEvidenceSnapshot
collect_physical_campaign_evidence = _implementation.collect_physical_campaign_evidence

# Explicit private test seam.  It retains injectable verifier/runtime/root/clock
# inputs but carries no production authority and is intentionally underscored.
_collect_physical_campaign_evidence = _implementation._collect_physical_campaign_evidence

__all__ = [
    "EVIDENCE_SNAPSHOT_SCHEMA",
    "EVIDENCE_SNAPSHOT_AUTHORITY",
    "MISSING_COMPLETION_GATES",
    "PhysicalCampaignEvidenceError",
    "PhysicalCampaignEvidenceSnapshot",
    "collect_physical_campaign_evidence",
]

del install_physical_campaign_evidence_production_boundary
