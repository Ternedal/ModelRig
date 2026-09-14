"""Public host-pinned facade for ADR-DC-030 exact-task human authority."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_execution_authorization_impl as _implementation
from ._improvement_pilot_exact_task_execution_authorization_production_boundary import (
    install_pilot_exact_task_execution_authorization_production_boundary,
)

install_pilot_exact_task_execution_authorization_production_boundary(_implementation)

PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotExactTaskExecutionAuthorizationError = (
    _implementation.PilotExactTaskExecutionAuthorizationError
)
PilotExactTaskExecutionAuthorization = _implementation.PilotExactTaskExecutionAuthorization
PilotExactTaskExecutionAuthorizationProof = (
    _implementation.PilotExactTaskExecutionAuthorizationProof
)
build_pilot_exact_task_execution_authorization = (
    _implementation.build_pilot_exact_task_execution_authorization
)
verify_pilot_exact_task_execution_authorization = (
    _implementation.verify_pilot_exact_task_execution_authorization
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_exact_task_execution_authorization = (
    _implementation._verify_pilot_exact_task_execution_authorization
)

__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskExecutionAuthorizationError",
    "PilotExactTaskExecutionAuthorization",
    "PilotExactTaskExecutionAuthorizationProof",
    "build_pilot_exact_task_execution_authorization",
    "verify_pilot_exact_task_execution_authorization",
]

del install_pilot_exact_task_execution_authorization_production_boundary
