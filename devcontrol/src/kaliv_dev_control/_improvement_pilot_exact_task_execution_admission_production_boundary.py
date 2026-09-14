"""Production host boundary for ADR-DC-033 exact-task execution admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from . import improvement_pilot_exact_task_execution_revalidation_attestation as _revalidation

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-execution-admission-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-execution-admission-ledger-v1"
)


class PilotExactTaskExecutionAdmissionProductionBoundaryError(ValueError):
    """Production exact-task execution admission state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
                "exact-task execution admission ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            "canonical exact-task execution admission ledger is not host-admin controlled"
        ) from exc


def _snapshot_signature(value: Any, *, name: str) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            f"exact detached {name} signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            f"{name} signature could not be snapshotted"
        ) from exc


def _snapshot_proof(
    value: Any,
) -> _revalidation.PilotExactTaskExecutionRevalidationAttestationProof:
    if type(value) is not _revalidation.PilotExactTaskExecutionRevalidationAttestationProof:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            "exact ADR-DC-032 revalidation-attestation proof is required"
        )
    try:
        return _revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
            value.to_dict()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            "ADR-DC-032 proof could not be snapshotted"
        ) from exc


def install_pilot_exact_task_execution_admission_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskExecutionAdmissionProductionBoundaryError(
            "exact-task execution admission implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_execution_admission_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def admit_pilot_exact_task_execution(
        *,
        revalidation_attestation_proof: Any,
        revalidation_attestation_signature: Any,
        execution_authorization_signature: Any,
        admission_attestation_signature: Any,
    ) -> Any:
        """Freshly reverify ADR-032 and durably consume its exact signed nonce."""
        try:
            supplied = _snapshot_proof(revalidation_attestation_proof)
            revalidation_signature = _snapshot_signature(
                revalidation_attestation_signature,
                name="ADR-DC-032 revalidation-attestation",
            )
            execution_signature = _snapshot_signature(
                execution_authorization_signature,
                name="ADR-DC-030 execution-authorization",
            )
            admission_signature = _snapshot_signature(
                admission_attestation_signature,
                name="ADR-DC-028 admission-attestation",
            )
        except PilotExactTaskExecutionAdmissionProductionBoundaryError as exc:
            raise implementation.PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission authority inputs are invalid"
            ) from exc

        try:
            fresh = _revalidation.verify_pilot_exact_task_execution_revalidation_attestation(
                attestation=supplied.attestation,
                signature=revalidation_signature,
                execution_authorization_signature=execution_signature,
                admission_attestation_signature=admission_signature,
            )
            implementation.require_fresh_revalidation_proof_identity(supplied, fresh)
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotExactTaskExecutionAdmissionError(
                "fresh ADR-DC-028/030/032 provenance verification failed"
            ) from exc

        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskExecutionAdmissionLedger(root)
            return implementation._admit_verified_exact_task_execution(
                supplied_proof=supplied,
                fresh_proof=fresh,
                ledger=ledger,
                now_provider=implementation._now_utc_seconds,
            )
        except (
            PilotExactTaskExecutionAdmissionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotExactTaskExecutionAdmissionError):
                raise
            raise implementation.PilotExactTaskExecutionAdmissionError(
                "host-controlled exact-task execution admission failed closed"
            ) from exc

    implementation.admit_pilot_exact_task_execution = admit_pilot_exact_task_execution
    setattr(implementation, marker, True)


__all__: list[str] = []
