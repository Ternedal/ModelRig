"""Public host-pinned facade for ADR-DC-054 human PR-mutation authority."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_pr_mutation_authorization_impl as _implementation
from ._improvement_pilot_exact_task_pr_mutation_authorization_production_boundary import (
    install_pilot_exact_task_pr_mutation_authorization_production_boundary,
)

install_pilot_exact_task_pr_mutation_authorization_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotExactTaskPrMutationAuthorizationError = (
    _implementation.PilotExactTaskPrMutationAuthorizationError
)
PilotExactTaskPrMutationAuthorization = (
    _implementation.PilotExactTaskPrMutationAuthorization
)
PilotExactTaskPrMutationAuthorizationProof = (
    _implementation.PilotExactTaskPrMutationAuthorizationProof
)
build_pilot_exact_task_pr_mutation_authorization = (
    _implementation.build_pilot_exact_task_pr_mutation_authorization
)
verify_pilot_exact_task_pr_mutation_authorization = (
    _implementation.verify_pilot_exact_task_pr_mutation_authorization
)

# Deterministic support seams only; production verification is host-pinned above.
_verify_pilot_exact_task_pr_mutation_authorization = (
    _implementation._verify_pilot_exact_task_pr_mutation_authorization
)
_require_requirements = _implementation._require_requirements
_require_live_requirements = _implementation._require_live_requirements

__all__ = [
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPrMutationAuthorizationError",
    "PilotExactTaskPrMutationAuthorization",
    "PilotExactTaskPrMutationAuthorizationProof",
    "build_pilot_exact_task_pr_mutation_authorization",
    "verify_pilot_exact_task_pr_mutation_authorization",
]

del install_pilot_exact_task_pr_mutation_authorization_production_boundary
