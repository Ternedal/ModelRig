"""Public host-pinned facade for ADR-DC-048 human remote-publication authority."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_remote_publication_authorization_impl as _implementation
from ._improvement_pilot_exact_task_remote_publication_authorization_production_boundary import (
    install_pilot_exact_task_remote_publication_authorization_production_boundary,
)

install_pilot_exact_task_remote_publication_authorization_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotExactTaskRemotePublicationAuthorizationError = (
    _implementation.PilotExactTaskRemotePublicationAuthorizationError
)
PilotExactTaskRemotePublicationAuthorization = (
    _implementation.PilotExactTaskRemotePublicationAuthorization
)
PilotExactTaskRemotePublicationAuthorizationProof = (
    _implementation.PilotExactTaskRemotePublicationAuthorizationProof
)
build_pilot_exact_task_remote_publication_authorization = (
    _implementation.build_pilot_exact_task_remote_publication_authorization
)
verify_pilot_exact_task_remote_publication_authorization = (
    _implementation.verify_pilot_exact_task_remote_publication_authorization
)

# Deterministic support seam only; production verification is host-pinned above.
_verify_pilot_exact_task_remote_publication_authorization = (
    _implementation._verify_pilot_exact_task_remote_publication_authorization
)
_require_requirements = _implementation._require_requirements
_require_live_requirements = _implementation._require_live_requirements

__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskRemotePublicationAuthorizationError",
    "PilotExactTaskRemotePublicationAuthorization",
    "PilotExactTaskRemotePublicationAuthorizationProof",
    "build_pilot_exact_task_remote_publication_authorization",
    "verify_pilot_exact_task_remote_publication_authorization",
]

del install_pilot_exact_task_remote_publication_authorization_production_boundary
