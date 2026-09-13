"""Public ADR-DC-013 live continuous-main-freeze facade.

The optional RSI/DC-L15 chain stays out of the package root. Importing this
facade self-installs the host-pinned watcher/runtime boundary.
"""
from __future__ import annotations

from . import _improvement_physical_campaign_main_freeze_impl as _implementation
from ._improvement_physical_campaign_main_freeze_production_boundary import (
    install_physical_campaign_main_freeze_production_boundary,
)

install_physical_campaign_main_freeze_production_boundary(_implementation)

MAIN_FREEZE_PROOF_SCHEMA = _implementation.MAIN_FREEZE_PROOF_SCHEMA
MAIN_FREEZE_PROOF_AUTHORITY = _implementation.MAIN_FREEZE_PROOF_AUTHORITY
REMAINING_COMPLETION_GATES = _implementation.REMAINING_COMPLETION_GATES
PhysicalCampaignMainFreezeError = _implementation.PhysicalCampaignMainFreezeError
PhysicalCampaignMainFreezeLease = _implementation.PhysicalCampaignMainFreezeLease
PhysicalCampaignMainFreezeProof = _implementation.PhysicalCampaignMainFreezeProof
begin_physical_campaign_main_freeze = _implementation.begin_physical_campaign_main_freeze
finalize_physical_campaign_main_freeze = _implementation.finalize_physical_campaign_main_freeze
abort_physical_campaign_main_freeze = _implementation.abort_physical_campaign_main_freeze

# Explicit deterministic test seams; never production authority.
_begin_physical_campaign_main_freeze = _implementation._begin_physical_campaign_main_freeze
_finalize_physical_campaign_main_freeze = _implementation._finalize_physical_campaign_main_freeze
_abort_physical_campaign_main_freeze = _implementation._abort_physical_campaign_main_freeze

__all__ = [
    "MAIN_FREEZE_PROOF_SCHEMA",
    "MAIN_FREEZE_PROOF_AUTHORITY",
    "REMAINING_COMPLETION_GATES",
    "PhysicalCampaignMainFreezeError",
    "PhysicalCampaignMainFreezeLease",
    "PhysicalCampaignMainFreezeProof",
    "begin_physical_campaign_main_freeze",
    "finalize_physical_campaign_main_freeze",
    "abort_physical_campaign_main_freeze",
]

del install_physical_campaign_main_freeze_production_boundary
