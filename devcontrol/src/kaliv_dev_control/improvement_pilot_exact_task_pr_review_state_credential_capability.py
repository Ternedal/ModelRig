"""Public host-pinned facade for ADR-DC-077 review-state read capability."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_pr_review_state_credential_capability_impl as _implementation
from ._improvement_pilot_exact_task_pr_review_state_credential_capability_production_boundary import (
    install_pilot_exact_task_pr_review_state_credential_capability_production_boundary,
)

install_pilot_exact_task_pr_review_state_credential_capability_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY
)
PilotExactTaskPrReviewStateCredentialCapabilityError = (
    _implementation.PilotExactTaskPrReviewStateCredentialCapabilityError
)
PilotExactTaskPrReviewStateCredentialCapability = (
    _implementation.PilotExactTaskPrReviewStateCredentialCapability
)
materialize_pilot_exact_task_pr_review_state_credential_capability = (
    _implementation.materialize_pilot_exact_task_pr_review_state_credential_capability
)

# Deterministic support seams only; production broker selection remains host-pinned.
_require_live_attestation = _implementation._require_live_attestation
_descriptor = _implementation._descriptor
_materialize_verified_pilot_exact_task_pr_review_state_credential_capability = (
    _implementation._materialize_verified_pilot_exact_task_pr_review_state_credential_capability
)
_get_live_pr_review_state_credential_capability_inputs = (
    _implementation._get_live_pr_review_state_credential_capability_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY",
    "PilotExactTaskPrReviewStateCredentialCapabilityError",
    "PilotExactTaskPrReviewStateCredentialCapability",
    "materialize_pilot_exact_task_pr_review_state_credential_capability",
]

del install_pilot_exact_task_pr_review_state_credential_capability_production_boundary
