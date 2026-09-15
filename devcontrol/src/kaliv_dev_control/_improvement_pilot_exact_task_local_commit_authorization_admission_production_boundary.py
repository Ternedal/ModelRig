"""Production host boundary for ADR-DC-045 local-commit authorization admission."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Callable
from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator, _require_host_controlled_ledger_root
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from . import improvement_pilot_exact_task_local_commit_authorization as _authorization
_POSIX_LEDGER = Path('/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-local-commit-authorization-admission-ledger-v1')
_WINDOWS_LEDGER = Path('C:\\Program Files\\ModelRig\\DevControl\\state\\rsi-pilot-exact-task-local-commit-authorization-admission-ledger-v1')

class PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError(ValueError):
    """Production ADR-DC-045 host state is unsafe or unavailable."""

def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == 'posix':
            path = _POSIX_LEDGER
        elif os.name == 'nt':
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('local-commit authorization admission ledger is unsupported on this platform')
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('canonical local-commit authorization admission ledger is not host-admin controlled') from exc

def _snapshot_signature(value: Any) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('exact detached ADR-DC-044 authorization signature is required')
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(json.loads(value.canonical_json()))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('ADR-DC-044 authorization signature could not be snapshotted') from exc

def _snapshot_proof(value: Any) -> Any:
    if type(value) is not _authorization.PilotExactTaskLocalCommitAuthorizationProof:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('exact ADR-DC-044 authorization proof is required')
    try:
        return _authorization.PilotExactTaskLocalCommitAuthorizationProof.from_mapping(value.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('ADR-DC-044 authorization proof could not be snapshotted') from exc

def _nondecreasing_admission_clock(implementation: Any) -> Callable[[], str]:
    last = None
    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(value, name='production local-commit admission clock')
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskLocalCommitAuthorizationAdmissionError('production local-commit admission clock is invalid') from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskLocalCommitAuthorizationAdmissionError('system clock moved backwards during local-commit authorization admission')
        last = current
        return value
    return now

def install_pilot_exact_task_local_commit_authorization_admission_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError('local-commit authorization admission implementation is unavailable')
    marker = '_production_pilot_exact_task_local_commit_authorization_admission_boundary_installed'
    if getattr(implementation, marker, False):
        return
    def admit_pilot_exact_task_local_commit_authorization(*, authorization_proof: Any, authorization_signature: Any, object_identity: Any) -> Any:
        try:
            supplied = _snapshot_proof(authorization_proof)
            signature = _snapshot_signature(authorization_signature)
            fresh = _authorization.verify_pilot_exact_task_local_commit_authorization(authorization=supplied.authorization, signature=signature)
            implementation.require_fresh_local_commit_authorization_proof_identity(supplied, fresh)
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotExactTaskLocalCommitAuthorizationAdmissionError('fresh ADR-DC-044 human authorization verification failed') from exc
        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskLocalCommitAuthorizationAdmissionLedger(root)
            return implementation._admit_verified_pilot_exact_task_local_commit_authorization(supplied_proof=supplied, fresh_proof=fresh, object_identity=object_identity, ledger=ledger, now_provider=_nondecreasing_admission_clock(implementation))
        except (PilotExactTaskLocalCommitAuthorizationAdmissionProductionBoundaryError, PhysicalHostStateError, ValueError, TypeError, AttributeError) as exc:
            if isinstance(exc, implementation.PilotExactTaskLocalCommitAuthorizationAdmissionError):
                raise
            raise implementation.PilotExactTaskLocalCommitAuthorizationAdmissionError('host-controlled local-commit authorization admission failed closed') from exc
    implementation.admit_pilot_exact_task_local_commit_authorization = admit_pilot_exact_task_local_commit_authorization
    setattr(implementation, marker, True)
__all__: list[str] = []
