"""Public host-pinned facade for ADR-DC-055 opaque GitHub push credential capability."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_remote_push_credential_capability_impl as _implementation
from ._improvement_pilot_exact_task_remote_push_credential_capability_production_boundary import (
    install_pilot_exact_task_remote_push_credential_capability_production_boundary,
)

install_pilot_exact_task_remote_push_credential_capability_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA
)
PilotExactTaskRemotePushCredentialCapabilityError = (
    _implementation.PilotExactTaskRemotePushCredentialCapabilityError
)
PilotExactTaskRemotePushCredentialCapability = (
    _implementation.PilotExactTaskRemotePushCredentialCapability
)
materialize_pilot_exact_task_remote_push_credential_capability = (
    _implementation.materialize_pilot_exact_task_remote_push_credential_capability
)

# Deterministic test seams only. Production loads one fixed host-controlled attestation.
GithubPushCredentialProviderAttestation = (
    _implementation.GithubPushCredentialProviderAttestation
)
_materialize_verified_pilot_exact_task_remote_push_credential_capability = (
    _implementation._materialize_verified_pilot_exact_task_remote_push_credential_capability
)
_get_live_remote_push_credential_capability_inputs = (
    _implementation._get_live_remote_push_credential_capability_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA",
    "PilotExactTaskRemotePushCredentialCapabilityError",
    "PilotExactTaskRemotePushCredentialCapability",
    "materialize_pilot_exact_task_remote_push_credential_capability",
]

del install_pilot_exact_task_remote_push_credential_capability_production_boundary
