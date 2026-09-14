"""Public host-pinned verification facade for ADR-DC-023 pilot-start authority."""
from __future__ import annotations

from . import _improvement_pilot_start_authorization_impl as _implementation
from ._improvement_pilot_start_authorization_production_boundary import (
    install_pilot_start_authorization_production_boundary,
)

install_pilot_start_authorization_production_boundary(_implementation)

# The public artifact parser owns the ADR-023 error boundary. Nested ADR-DC-022
# replay validation remains fail-closed, but callers never need to understand a
# lower-layer exception taxonomy in order to handle an invalid start artifact.
_original_authorization_from_mapping = (
    _implementation.PilotStartAuthorization.from_mapping.__func__
)


def _normalized_authorization_from_mapping(cls, value):
    try:
        return _original_authorization_from_mapping(cls, value)
    except _implementation.PilotStartAuthorizationError:
        raise
    except ValueError as exc:
        raise _implementation.PilotStartAuthorizationError(
            "nested runtime preflight proof replay validation failed"
        ) from exc


_implementation.PilotStartAuthorization.from_mapping = classmethod(
    _normalized_authorization_from_mapping
)

PILOT_START_AUTHORIZATION_SCHEMA = _implementation.PILOT_START_AUTHORIZATION_SCHEMA
PILOT_START_AUTHORIZATION_PROOF_SCHEMA = (
    _implementation.PILOT_START_AUTHORIZATION_PROOF_SCHEMA
)
PILOT_START_AUTHORIZATION_AUTHORITY = (
    _implementation.PILOT_START_AUTHORIZATION_AUTHORITY
)
PILOT_START_AUTHORIZATION_PROOF_AUTHORITY = (
    _implementation.PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
)
PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID
)
PILOT_START_AUTHORIZATION_INTENT = _implementation.PILOT_START_AUTHORIZATION_INTENT
PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS = (
    _implementation.PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS
)
PilotStartAuthorizationError = _implementation.PilotStartAuthorizationError
PilotStartAuthorization = _implementation.PilotStartAuthorization
PilotStartAuthorizationProof = _implementation.PilotStartAuthorizationProof
build_pilot_start_authorization = _implementation.build_pilot_start_authorization
verify_pilot_start_authorization = _implementation.verify_pilot_start_authorization

# Deterministic test seam only; production verification is host-pinned above.
_verify_pilot_start_authorization = _implementation._verify_pilot_start_authorization

__all__ = [
    "PILOT_START_AUTHORIZATION_SCHEMA",
    "PILOT_START_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_START_AUTHORIZATION_AUTHORITY",
    "PILOT_START_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_START_AUTHORIZATION_INTENT",
    "PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotStartAuthorizationError",
    "PilotStartAuthorization",
    "PilotStartAuthorizationProof",
    "build_pilot_start_authorization",
    "verify_pilot_start_authorization",
]

del _normalized_authorization_from_mapping
del _original_authorization_from_mapping
del install_pilot_start_authorization_production_boundary
