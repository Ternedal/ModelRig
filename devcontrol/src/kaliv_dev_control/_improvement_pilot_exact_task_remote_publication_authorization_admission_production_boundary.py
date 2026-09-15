"""Production host boundary for ADR-DC-052 remote-publication authorization admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from . import improvement_pilot_exact_task_remote_publication_authorization as _authorization

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-remote-publication-authorization-admission-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-remote-publication-authorization-admission-ledger-v1"
)


class PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(ValueError):
    """Production ADR-DC-052 host state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
                "remote-publication authorization admission ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "canonical remote-publication authorization admission ledger is not host-admin controlled"
        ) from exc


def _snapshot_signature(value: Any) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "exact detached ADR-DC-051 authorization signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "ADR-DC-051 authorization signature could not be snapshotted"
        ) from exc


def _snapshot_proof(value: Any) -> Any:
    if type(value) is not _authorization.PilotExactTaskRemotePublicationAuthorizationProof:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "exact ADR-DC-051 authorization proof is required"
        )
    try:
        return _authorization.PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "ADR-DC-051 authorization proof could not be snapshotted"
        ) from exc


def _nondecreasing_admission_clock(implementation: Any) -> Callable[[], str]:
    last = None

    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(
                value, name="production remote-publication admission clock"
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "production remote-publication admission clock is invalid"
            ) from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "system clock moved backwards during remote-publication authorization admission"
            )
        last = current
        return value

    return now


def install_pilot_exact_task_remote_publication_authorization_admission_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError(
            "remote-publication authorization admission implementation is unavailable"
        )
    marker = (
        "_production_pilot_exact_task_remote_publication_authorization_admission_boundary_installed"
    )
    if getattr(implementation, marker, False):
        return

    def admit_pilot_exact_task_remote_publication_authorization(
        *,
        authorization_proof: Any,
        authorization_signature: Any,
        remote_head_observation: Any,
    ) -> Any:
        try:
            supplied = _snapshot_proof(authorization_proof)
            signature = _snapshot_signature(authorization_signature)
            fresh = _authorization.verify_pilot_exact_task_remote_publication_authorization(
                authorization=supplied.authorization,
                signature=signature,
            )
            implementation.require_fresh_remote_publication_authorization_proof_identity(
                supplied, fresh
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "fresh ADR-DC-051 human authorization verification failed"
            ) from exc
        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskRemotePublicationAuthorizationAdmissionLedger(
                root
            )
            return implementation._admit_verified_pilot_exact_task_remote_publication_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                remote_head_observation=remote_head_observation,
                ledger=ledger,
                now_provider=_nondecreasing_admission_clock(implementation),
            )
        except (
            PilotExactTaskRemotePublicationAuthorizationAdmissionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(
                exc,
                implementation.PilotExactTaskRemotePublicationAuthorizationAdmissionError,
            ):
                raise
            raise implementation.PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "host-controlled remote-publication authorization admission failed closed"
            ) from exc

    implementation.admit_pilot_exact_task_remote_publication_authorization = (
        admit_pilot_exact_task_remote_publication_authorization
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
