"""Public host-pinned facade for ADR-DC-099 fresh product-pilot human GO."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_product_pilot_fresh_go_impl as _implementation
from ._improvement_pilot_exact_task_product_pilot_fresh_go_production_boundary import (
    install_pilot_exact_task_product_pilot_fresh_go_production_boundary,
)

install_pilot_exact_task_product_pilot_fresh_go_production_boundary(_implementation)

PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS = (
    _implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS
)
PilotExactTaskProductPilotFreshGoError = (
    _implementation.PilotExactTaskProductPilotFreshGoError
)
PilotExactTaskProductPilotFreshGoClaim = (
    _implementation.PilotExactTaskProductPilotFreshGoClaim
)
PilotExactTaskProductPilotFreshGoProof = (
    _implementation.PilotExactTaskProductPilotFreshGoProof
)
build_pilot_exact_task_product_pilot_fresh_go_claim = (
    _implementation.build_pilot_exact_task_product_pilot_fresh_go_claim
)
verify_pilot_exact_task_product_pilot_fresh_go = (
    _implementation.verify_pilot_exact_task_product_pilot_fresh_go
)

# Deterministic contract seam only; production verifier is host-pinned above.
_verify_pilot_exact_task_product_pilot_fresh_go = (
    _implementation._verify_pilot_exact_task_product_pilot_fresh_go
)

__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS",
    "PilotExactTaskProductPilotFreshGoError",
    "PilotExactTaskProductPilotFreshGoClaim",
    "PilotExactTaskProductPilotFreshGoProof",
    "build_pilot_exact_task_product_pilot_fresh_go_claim",
    "verify_pilot_exact_task_product_pilot_fresh_go",
]

del install_pilot_exact_task_product_pilot_fresh_go_production_boundary
