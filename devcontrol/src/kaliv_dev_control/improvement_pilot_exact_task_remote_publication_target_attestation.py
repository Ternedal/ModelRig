"""Public host-pinned facade for ADR-DC-049 remote target attestation."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_remote_publication_target_attestation_impl as _implementation
from ._improvement_pilot_exact_task_remote_publication_target_attestation_production_boundary import (
    install_pilot_exact_task_remote_publication_target_attestation_production_boundary,
)

install_pilot_exact_task_remote_publication_target_attestation_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION
)
PilotExactTaskRemotePublicationTargetAttestationError = (
    _implementation.PilotExactTaskRemotePublicationTargetAttestationError
)
PilotExactTaskRemotePublicationTargetPolicy = (
    _implementation.PilotExactTaskRemotePublicationTargetPolicy
)
PilotExactTaskRemotePublicationTargetAttestation = (
    _implementation.PilotExactTaskRemotePublicationTargetAttestation
)
attest_pilot_exact_task_remote_publication_target = (
    _implementation.attest_pilot_exact_task_remote_publication_target
)

# Deterministic support seams only; production target selection is host-pinned above.
_require_proof = _implementation._require_proof
_require_live_proof = _implementation._require_live_proof
require_fresh_remote_publication_authorization_proof_identity = (
    _implementation.require_fresh_remote_publication_authorization_proof_identity
)
_destination_ref = _implementation._destination_ref
_attest_verified_pilot_exact_task_remote_publication_target = (
    _implementation._attest_verified_pilot_exact_task_remote_publication_target
)
_get_live_remote_publication_target_attestation_inputs = (
    _implementation._get_live_remote_publication_target_attestation_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_POLICY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_PROVIDER",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_HOST",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_REPOSITORY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_NAMESPACE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_DESTINATION_REF_DERIVATION",
    "PilotExactTaskRemotePublicationTargetAttestationError",
    "PilotExactTaskRemotePublicationTargetPolicy",
    "PilotExactTaskRemotePublicationTargetAttestation",
    "attest_pilot_exact_task_remote_publication_target",
]

del install_pilot_exact_task_remote_publication_target_attestation_production_boundary
