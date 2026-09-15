"""Production host boundary for ADR-DC-055 opaque GitHub push credential capability."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _require_posix_host_control,
    _require_windows_host_control,
)
from .trusted_git_runtime_model import _has_linkish_component

_POSIX_ATTESTATION = Path(
    "/etc/modelrig/devcontrol/authority/github-push-credential-provider-attestation-v1.json"
)
_WINDOWS_ATTESTATION = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\github-push-credential-provider-attestation-v1.json"
)
_MAX_ATTESTATION_BYTES = 64 * 1024


class PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(ValueError):
    """Production credential-provider attestation is unavailable or unsafe."""


def _canonical_attestation_path() -> Path:
    if os.name == "posix":
        return _POSIX_ATTESTATION
    if os.name == "nt":
        return _WINDOWS_ATTESTATION
    raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
        "opaque GitHub credential provider is unsupported on this platform"
    )


def _load_host_provider_attestation(implementation: Any) -> Any:
    try:
        _require_elevated_operator()
        path = _canonical_attestation_path()
        if not path.is_absolute() or _has_linkish_component(path):
            raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
                "credential provider attestation path is unsafe"
            )
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > _MAX_ATTESTATION_BYTES
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
                "credential provider attestation must be one bounded regular file"
            )
        if os.name == "posix":
            _require_posix_host_control(path, before)
        elif os.name == "nt":
            _require_windows_host_control(path, before)
        after = path.lstat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
                "credential provider attestation changed during host-control validation"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > _MAX_ATTESTATION_BYTES:
            raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
                "credential provider attestation bytes are invalid"
            )
        final = path.lstat()
        if (after.st_dev, after.st_ino) != (final.st_dev, final.st_ino):
            raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
                "credential provider attestation changed during read"
            )
        parsed = json.loads(payload.decode("utf-8", errors="strict"))
        return implementation.GithubPushCredentialProviderAttestation.from_mapping(parsed)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        PhysicalHostStateError,
        PhysicalRequestAuthorityKeyringError,
        ValueError,
        TypeError,
        AttributeError,
    ) as exc:
        if isinstance(exc, implementation.PilotExactTaskRemotePushCredentialCapabilityError):
            raise
        raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
            "host-controlled GitHub credential provider attestation failed closed"
        ) from exc


def install_pilot_exact_task_remote_push_credential_capability_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError(
            "credential capability implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_remote_push_credential_capability_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def materialize_pilot_exact_task_remote_push_credential_capability(
        push_capability_requirements: Any,
    ) -> Any:
        try:
            attestation = _load_host_provider_attestation(implementation)
            return implementation._materialize_verified_pilot_exact_task_remote_push_credential_capability(
                push_capability_requirements=push_capability_requirements,
                provider_attestation=attestation,
                provider_attestation_host_controlled=True,
                now_provider=implementation._now_utc_seconds,
            )
        except (
            PilotExactTaskRemotePushCredentialCapabilityProductionBoundaryError,
            PhysicalHostStateError,
            PhysicalRequestAuthorityKeyringError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotExactTaskRemotePushCredentialCapabilityError):
                raise
            raise implementation.PilotExactTaskRemotePushCredentialCapabilityError(
                "host-controlled opaque GitHub credential capability failed closed"
            ) from exc

    implementation.materialize_pilot_exact_task_remote_push_credential_capability = (
        materialize_pilot_exact_task_remote_push_credential_capability
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
