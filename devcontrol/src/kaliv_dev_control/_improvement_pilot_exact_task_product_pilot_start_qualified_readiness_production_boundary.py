"""Host-pinned production verification for ADR-DC-099 qualified readiness."""
from __future__ import annotations

import json
from typing import Any

from . import _improvement_human_pilot_decision_impl as _human
from . import _improvement_pilot_exact_task_product_pilot_start_qualified_readiness_impl as _impl
from ._improvement_human_pilot_decision_production_boundary import (
    _canonical_human_pilot_decision_verifier,
)
from .asymmetric_authority import DetachedEd25519AuthoritySignature


class PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(ValueError):
    """Canonical human authority for ADR-DC-099 is unavailable or inconsistent."""


def _snapshot_signature(value: Any) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "exact detached fresh human GO signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO signature could not be snapshotted"
        ) from exc


def _decision_from_proof(proof: _human.HumanPilotDecisionProof) -> _human.HumanPilotDecision:
    return _human.HumanPilotDecision(
        decision_id=proof.decision_id,
        completion_proof_sha256=proof.completion_proof_sha256,
        campaign_id=proof.campaign_id,
        task_id=proof.task_id,
        task_sha256=proof.task_sha256,
        repository=proof.repository,
        base_sha=proof.base_sha,
        requested_main_sha=proof.requested_main_sha,
        decision_maker_actor_id=proof.decision_maker_actor_id,
        decision=proof.decision,
        operator_surface=proof.operator_surface,
        allowed_task_ids=proof.allowed_task_ids,
        workspace_root_path_sha256=proof.workspace_root_path_sha256,
        local_commits_allowed=proof.local_commits_allowed,
        notes=proof.notes,
        decided_at_utc=proof.decided_at_utc,
    )


def _reverify_fresh_human_go(
    completion_proof: Any,
    proof: _human.HumanPilotDecisionProof,
    signature: DetachedEd25519AuthoritySignature,
) -> None:
    if type(proof) is not _human.HumanPilotDecisionProof:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "exact fresh HumanPilotDecisionProof is required"
        )
    try:
        replayed = _human.HumanPilotDecisionProof.from_mapping(proof.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO proof replay validation failed"
        ) from exc
    if replayed != proof or replayed.sha256 != proof.sha256:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO proof replay identity mismatch"
        )

    exact_signature = _snapshot_signature(signature)
    decision = _decision_from_proof(proof)
    if (
        exact_signature.sha256 != proof.signature_sha256
        or exact_signature.key_id != proof.key_id
        or exact_signature.issuer_actor_id != proof.issuer_actor_id
        or exact_signature.issuer_system_id != proof.issuer_system_id
        or exact_signature.signed_at_utc != proof.decided_at_utc
    ):
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO signature metadata does not match proof"
        )

    verifier = _canonical_human_pilot_decision_verifier(
        issuer_system_id=_human.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID
    )
    try:
        verified = _human._verify_human_pilot_decision(
            completion_proof=completion_proof,
            decision=decision,
            signature=exact_signature,
            verifier=verifier,
            now_provider=lambda: proof.verified_at_utc,
        )
    except (ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO authority verification failed"
        ) from exc
    if verified != proof or verified.sha256 != proof.sha256:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "fresh human GO verified proof identity mismatch"
        )


def install_pilot_exact_task_product_pilot_start_qualified_readiness_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError(
            "qualified readiness implementation is unavailable"
        )
    if getattr(implementation, "_production_qualified_readiness_boundary_installed", False):
        return

    private_evaluate = (
        implementation._evaluate_verified_pilot_exact_task_product_pilot_start_qualified_readiness
    )

    def evaluate_pilot_exact_task_product_pilot_start_qualified_readiness(
        *,
        fresh_human_go_completion_proof,
        fresh_human_go_proof,
        fresh_human_go_signature,
        product_pilot_lineage_attestation,
        post_production_activation_attestation,
    ):
        _reverify_fresh_human_go(
            fresh_human_go_completion_proof,
            fresh_human_go_proof,
            fresh_human_go_signature,
        )
        return private_evaluate(
            fresh_human_go_proof=fresh_human_go_proof,
            product_pilot_lineage_attestation=product_pilot_lineage_attestation,
            post_production_activation_attestation=post_production_activation_attestation,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.evaluate_pilot_exact_task_product_pilot_start_qualified_readiness = (
        evaluate_pilot_exact_task_product_pilot_start_qualified_readiness
    )
    implementation._production_qualified_readiness_boundary_installed = True


__all__ = [
    "PilotExactTaskProductPilotStartQualifiedReadinessProductionBoundaryError",
    "install_pilot_exact_task_product_pilot_start_qualified_readiness_production_boundary",
]
