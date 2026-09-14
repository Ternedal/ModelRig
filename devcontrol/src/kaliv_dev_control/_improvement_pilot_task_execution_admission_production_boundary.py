"""Production host boundary for ADR-DC-029 exact task execution admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .asymmetric_authority import DetachedEd25519AuthoritySignature
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from . import improvement_pilot_execution_admission_attestation as _att

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-task-execution-admission-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-task-execution-admission-ledger-v1"
)


class PilotTaskExecutionAdmissionProductionBoundaryError(ValueError):
    """Production exact-task admission state or upstream authority is unsafe."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotTaskExecutionAdmissionProductionBoundaryError(
                "task execution admission ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "canonical task execution admission ledger is not host-admin controlled"
        ) from exc


def _snapshot_signature(value: Any) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "exact detached ADR-DC-028 attestation signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "ADR-DC-028 attestation signature could not be snapshotted"
        ) from exc


def _require_live_start_receipt(value: Any) -> None:
    if type(value) is not _att.PilotExecutionAdmissionAttestationProof:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "exact ADR-DC-028 attestation proof is required"
        )
    try:
        receipt = value.attestation.packet.admission_requirements.start_receipt
    except AttributeError as exc:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "ADR-DC-028 proof has no bound start receipt"
        ) from exc
    if getattr(receipt, "transaction_authenticated", False) is not True:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "task execution admission requires the live ADR-DC-025 consumption transaction"
        )


def _snapshot_proof(value: Any) -> _att.PilotExecutionAdmissionAttestationProof:
    _require_live_start_receipt(value)
    try:
        return _att.PilotExecutionAdmissionAttestationProof.from_mapping(value.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "ADR-DC-028 proof could not be snapshotted"
        ) from exc


def install_pilot_task_execution_admission_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotTaskExecutionAdmissionProductionBoundaryError(
            "task execution admission implementation is unavailable"
        )
    if getattr(
        implementation,
        "_production_pilot_task_execution_admission_boundary_installed",
        False,
    ):
        return

    def admit_pilot_task_execution(
        *,
        attestation_proof: Any,
        attestation_signature: Any,
    ) -> Any:
        """Freshly verify ADR-028 and durably admit its one exact live task."""
        try:
            # The liveness check intentionally happens before snapshotting.  A
            # durable/reloaded ADR-025 receipt is evidence, not live admission
            # authority, even when nested in an otherwise valid ADR-028 proof.
            supplied = _snapshot_proof(attestation_proof)
            signature = _snapshot_signature(attestation_signature)
        except PilotTaskExecutionAdmissionProductionBoundaryError as exc:
            raise implementation.PilotTaskExecutionAdmissionError(
                "task execution admission authority inputs are invalid"
            ) from exc

        try:
            fresh = _att.verify_pilot_execution_admission_attestation(
                attestation=supplied.attestation,
                signature=signature,
            )
            implementation.require_fresh_proof_identity(supplied, fresh)
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotTaskExecutionAdmissionError(
                "fresh ADR-DC-028 attestation provenance verification failed"
            ) from exc

        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotTaskExecutionAdmissionLedger(root)
            return implementation._admit_verified_pilot_task_execution(
                supplied_proof=supplied,
                fresh_proof=fresh,
                ledger=ledger,
                now_provider=implementation._now_utc_seconds,
            )
        except (
            PilotTaskExecutionAdmissionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotTaskExecutionAdmissionError):
                raise
            raise implementation.PilotTaskExecutionAdmissionError(
                "host-controlled task execution admission failed closed"
            ) from exc

    implementation.admit_pilot_task_execution = admit_pilot_task_execution
    implementation._production_pilot_task_execution_admission_boundary_installed = True


__all__: list[str] = []
