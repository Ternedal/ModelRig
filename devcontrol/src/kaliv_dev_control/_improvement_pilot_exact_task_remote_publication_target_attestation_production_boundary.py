"""Production host boundary for ADR-DC-049 remote target attestation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from . import improvement_pilot_exact_task_remote_publication_authorization as remote_auth

_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/publication/"
    "rsi-pilot-exact-task-remote-publication-target-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\publication\rsi-pilot-exact-task-remote-publication-target-policy-v1.json"
)


class PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
    ValueError
):
    """Production remote-target policy is unavailable or not host controlled."""


def _canonical_target_policy_path() -> Path:
    if os.name == "posix":
        return _POSIX_POLICY
    if os.name == "nt":
        return _WINDOWS_POLICY
    raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
        "remote target policy is unsupported on this platform"
    )


def _load_target_policy_at(
    implementation: Any,
    path: Path,
    *,
    require_host_control: bool = True,
) -> Any:
    try:
        payload = _read_keyring_bytes(
            Path(path),
            require_host_control=require_host_control,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target policy could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target policy is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target policy must be an object"
        )
    try:
        policy = implementation.PilotExactTaskRemotePublicationTargetPolicy.from_mapping(
            value
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target policy is structurally invalid"
        ) from exc
    if payload != policy.canonical_json().encode("utf-8"):
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target policy is not canonical"
        )
    return policy


def _canonical_target_policy(implementation: Any) -> Any:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target attestation requires an elevated host operator"
        ) from exc
    return _load_target_policy_at(
        implementation,
        _canonical_target_policy_path(),
        require_host_control=True,
    )


def install_pilot_exact_task_remote_publication_target_attestation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskRemotePublicationTargetAttestationProductionBoundaryError(
            "remote target attestation implementation is unavailable"
        )
    marker = (
        "_production_pilot_exact_task_remote_publication_target_attestation_boundary_installed"
    )
    if getattr(implementation, marker, False):
        return

    private_attest = (
        implementation._attest_verified_pilot_exact_task_remote_publication_target
    )

    def attest_pilot_exact_task_remote_publication_target(
        *,
        authorization_proof: Any,
        authorization_signature: Any,
    ) -> Any:
        proof = implementation._require_live_proof(authorization_proof)
        authorization = proof.authorization
        requirements = authorization.local_commit_publication_requirements
        try:
            fresh_proof = (
                remote_auth.verify_pilot_exact_task_remote_publication_authorization(
                    local_commit_publication_requirements=requirements,
                    authorization=authorization,
                    signature=authorization_signature,
                )
            )
            implementation.require_fresh_remote_publication_authorization_proof_identity(
                proof,
                fresh_proof,
            )
            policy = _canonical_target_policy(implementation)
        except implementation.PilotExactTaskRemotePublicationTargetAttestationError:
            raise
        except Exception as exc:
            raise implementation.PilotExactTaskRemotePublicationTargetAttestationError(
                "host-controlled remote target authority is unavailable"
            ) from exc
        return private_attest(
            authorization_proof=proof,
            fresh_authorization_proof=fresh_proof,
            target_policy=policy,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.attest_pilot_exact_task_remote_publication_target = (
        attest_pilot_exact_task_remote_publication_target
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
