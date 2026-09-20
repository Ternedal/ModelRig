"""Host-pinned production verification for ADR-DC-099 fresh product-pilot GO."""
from __future__ import annotations

from typing import Any

from ._improvement_human_pilot_decision_production_boundary import (
    _canonical_human_pilot_decision_verifier,
)


class PilotExactTaskProductPilotFreshGoProductionBoundaryError(ValueError):
    """Canonical human product-pilot GO authority is unavailable."""


def install_pilot_exact_task_product_pilot_fresh_go_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskProductPilotFreshGoProductionBoundaryError(
            "fresh product-pilot GO implementation is unavailable"
        )
    if getattr(implementation, "_production_product_pilot_fresh_go_installed", False):
        return

    private_verify = implementation._verify_pilot_exact_task_product_pilot_fresh_go

    def verify_pilot_exact_task_product_pilot_fresh_go(
        *,
        claim,
        signature,
        product_pilot_lineage_attestation,
        post_production_activation_attestation,
        verifier=None,
    ):
        if verifier is not None:
            raise implementation.PilotExactTaskProductPilotFreshGoError(
                "caller-selected product-pilot GO verifier is forbidden"
            )
        canonical = _canonical_human_pilot_decision_verifier(
            issuer_system_id=implementation.PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID
        )
        return private_verify(
            claim=claim,
            signature=signature,
            product_pilot_lineage_attestation=product_pilot_lineage_attestation,
            post_production_activation_attestation=post_production_activation_attestation,
            verifier=canonical,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.verify_pilot_exact_task_product_pilot_fresh_go = (
        verify_pilot_exact_task_product_pilot_fresh_go
    )
    implementation._production_product_pilot_fresh_go_installed = True


__all__ = [
    "PilotExactTaskProductPilotFreshGoProductionBoundaryError",
    "install_pilot_exact_task_product_pilot_fresh_go_production_boundary",
]
