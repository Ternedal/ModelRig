"""Public host-pinned facade for ADR-DC-098 product-pilot lineage attestation."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_product_pilot_lineage_attestation_impl as _implementation
from ._improvement_pilot_exact_task_product_pilot_lineage_attestation_production_boundary import (
    install_pilot_exact_task_product_pilot_lineage_attestation_production_boundary,
)

install_pilot_exact_task_product_pilot_lineage_attestation_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA
)
PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY
)
PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE
)
PilotExactTaskProductPilotLineageAttestationError = (
    _implementation.PilotExactTaskProductPilotLineageAttestationError
)
PilotExactTaskProductPilotLineageAttestationReceipt = (
    _implementation.PilotExactTaskProductPilotLineageAttestationReceipt
)
attest_pilot_exact_task_product_pilot_lineage = (
    _implementation.attest_pilot_exact_task_product_pilot_lineage
)

# Deterministic support seam only; production verification is host-pinned above.
_attest_verified_pilot_exact_task_product_pilot_lineage = (
    _implementation._attest_verified_pilot_exact_task_product_pilot_lineage
)
_historical_chain = _implementation._historical_chain

__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE",
    "PilotExactTaskProductPilotLineageAttestationError",
    "PilotExactTaskProductPilotLineageAttestationReceipt",
    "attest_pilot_exact_task_product_pilot_lineage",
]

del install_pilot_exact_task_product_pilot_lineage_attestation_production_boundary
