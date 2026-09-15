"""Public host-pinned facade for ADR-DC-068 human reviewer-request authority."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_pr_reviewer_request_authorization_impl as _implementation
from ._improvement_pilot_exact_task_pr_reviewer_request_authorization_production_boundary import (
    install_pilot_exact_task_pr_reviewer_request_authorization_production_boundary,
)

install_pilot_exact_task_pr_reviewer_request_authorization_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotExactTaskPrReviewerRequestAuthorizationError = (
    _implementation.PilotExactTaskPrReviewerRequestAuthorizationError
)
PilotExactTaskPrReviewerRequestAuthorization = (
    _implementation.PilotExactTaskPrReviewerRequestAuthorization
)
PilotExactTaskPrReviewerRequestAuthorizationProof = (
    _implementation.PilotExactTaskPrReviewerRequestAuthorizationProof
)
build_pilot_exact_task_pr_reviewer_request_authorization = (
    _implementation.build_pilot_exact_task_pr_reviewer_request_authorization
)
verify_pilot_exact_task_pr_reviewer_request_authorization = (
    _implementation.verify_pilot_exact_task_pr_reviewer_request_authorization
)

# Deterministic support seams only; production verification is host-pinned above.
_verify_pilot_exact_task_pr_reviewer_request_authorization = (
    _implementation._verify_pilot_exact_task_pr_reviewer_request_authorization
)
_require_attestation = _implementation._require_attestation
_require_live_attestation = _implementation._require_live_attestation
_prior_nonces = _implementation._prior_nonces

__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPrReviewerRequestAuthorizationError",
    "PilotExactTaskPrReviewerRequestAuthorization",
    "PilotExactTaskPrReviewerRequestAuthorizationProof",
    "build_pilot_exact_task_pr_reviewer_request_authorization",
    "verify_pilot_exact_task_pr_reviewer_request_authorization",
]

del install_pilot_exact_task_pr_reviewer_request_authorization_production_boundary
