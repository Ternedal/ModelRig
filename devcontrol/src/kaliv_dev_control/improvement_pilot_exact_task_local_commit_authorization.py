"""Public host-pinned facade for ADR-DC-044 exact local-commit human authority."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_local_commit_authorization_impl as _implementation
from ._improvement_pilot_exact_task_local_commit_authorization_production_boundary import (
    install_pilot_exact_task_local_commit_authorization_production_boundary,
)

install_pilot_exact_task_local_commit_authorization_production_boundary(_implementation)

PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotExactTaskLocalCommitAuthorizationError = (
    _implementation.PilotExactTaskLocalCommitAuthorizationError
)
PilotExactTaskLocalCommitAuthorization = (
    _implementation.PilotExactTaskLocalCommitAuthorization
)
PilotExactTaskLocalCommitAuthorizationProof = (
    _implementation.PilotExactTaskLocalCommitAuthorizationProof
)
build_pilot_exact_task_local_commit_authorization = (
    _implementation.build_pilot_exact_task_local_commit_authorization
)
verify_pilot_exact_task_local_commit_authorization = (
    _implementation.verify_pilot_exact_task_local_commit_authorization
)

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_exact_task_local_commit_authorization = (
    _implementation._verify_pilot_exact_task_local_commit_authorization
)

__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskLocalCommitAuthorizationError",
    "PilotExactTaskLocalCommitAuthorization",
    "PilotExactTaskLocalCommitAuthorizationProof",
    "build_pilot_exact_task_local_commit_authorization",
    "verify_pilot_exact_task_local_commit_authorization",
]

del install_pilot_exact_task_local_commit_authorization_production_boundary
