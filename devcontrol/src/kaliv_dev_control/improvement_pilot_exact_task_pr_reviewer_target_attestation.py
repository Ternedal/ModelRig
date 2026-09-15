"""Public host-pinned facade for ADR-DC-067 reviewer target attestation."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_pr_reviewer_target_attestation_impl as _implementation
from ._improvement_pilot_exact_task_pr_reviewer_target_attestation_production_boundary import (
    install_pilot_exact_task_pr_reviewer_target_attestation_production_boundary,
)

install_pilot_exact_task_pr_reviewer_target_attestation_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE
)
PilotExactTaskPrReviewerTargetAttestationError = (
    _implementation.PilotExactTaskPrReviewerTargetAttestationError
)
PilotExactTaskPrReviewerTargetPolicy = _implementation.PilotExactTaskPrReviewerTargetPolicy
PilotExactTaskPrReviewerTargetAttestation = (
    _implementation.PilotExactTaskPrReviewerTargetAttestation
)
attest_pilot_exact_task_pr_reviewer_target = (
    _implementation.attest_pilot_exact_task_pr_reviewer_target
)

# Deterministic support seams; production reviewer choice remains host-pinned above.
_require_live_requirements = _implementation._require_live_requirements
_attest_verified_pilot_exact_task_pr_reviewer_target = (
    _implementation._attest_verified_pilot_exact_task_pr_reviewer_target
)
_get_live_pr_reviewer_target_attestation_inputs = (
    _implementation._get_live_pr_reviewer_target_attestation_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE",
    "PilotExactTaskPrReviewerTargetAttestationError",
    "PilotExactTaskPrReviewerTargetPolicy",
    "PilotExactTaskPrReviewerTargetAttestation",
    "attest_pilot_exact_task_pr_reviewer_target",
]

del install_pilot_exact_task_pr_reviewer_target_attestation_production_boundary
