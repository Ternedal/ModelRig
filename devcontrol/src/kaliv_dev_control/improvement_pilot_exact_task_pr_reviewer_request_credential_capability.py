"""Public host-pinned facade for ADR-DC-071 reviewer-request credentials."""
from __future__ import annotations

from . import (
    _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_impl
    as _implementation,
)
from ._improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary import (
    install_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary,
)

install_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION_SET = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION_SET
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN
)
PilotExactTaskPrReviewerRequestCredentialCapabilityError = (
    _implementation.PilotExactTaskPrReviewerRequestCredentialCapabilityError
)
PilotExactTaskPrReviewerRequestCredentialCapability = (
    _implementation.PilotExactTaskPrReviewerRequestCredentialCapability
)
materialize_pilot_exact_task_pr_reviewer_request_credential_capability = (
    _implementation.materialize_pilot_exact_task_pr_reviewer_request_credential_capability
)

# Deterministic support seams only; production descriptor is host-pinned above.
_materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability = (
    _implementation._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability
)
_get_live_pr_reviewer_request_credential_capability_inputs = (
    _implementation._get_live_pr_reviewer_request_credential_capability_inputs
)
_require_live_observation = _implementation._require_live_observation
_descriptor = _implementation._descriptor

__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION_SET",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN",
    "PilotExactTaskPrReviewerRequestCredentialCapabilityError",
    "PilotExactTaskPrReviewerRequestCredentialCapability",
    "materialize_pilot_exact_task_pr_reviewer_request_credential_capability",
]

del install_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary
