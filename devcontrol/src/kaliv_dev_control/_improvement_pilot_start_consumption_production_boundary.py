"""Production host boundary for ADR-DC-025 pilot-start consumption."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import _improvement_pilot_start_consumption_impl as _impl
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from . import improvement_pilot_start_authorization as _start_auth

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-start-consumption-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-consumption-ledger-v1"
)


class PilotStartConsumptionProductionBoundaryError(ValueError):
    """Production pilot-start replay state or upstream authority is unsafe."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotStartConsumptionProductionBoundaryError(
                "pilot-start consumption ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotStartConsumptionProductionBoundaryError(
            "canonical pilot-start consumption ledger is not host-admin controlled"
        ) from exc


def _snapshot_signature(
    value: Any,
    *,
    name: str,
) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotStartConsumptionProductionBoundaryError(
            f"exact detached {name} signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotStartConsumptionProductionBoundaryError(
            f"detached {name} signature could not be snapshotted"
        ) from exc


def _snapshot_proof(value: Any) -> Any:
    if type(value) is not _start_auth.PilotStartAuthorizationProof:
        raise PilotStartConsumptionProductionBoundaryError(
            "exact ADR-DC-024 pilot-start authorization proof is required"
        )
    try:
        return _start_auth.PilotStartAuthorizationProof.from_mapping(value.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotStartConsumptionProductionBoundaryError(
            "ADR-DC-024 proof could not be snapshotted"
        ) from exc


def install_pilot_start_consumption_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotStartConsumptionProductionBoundaryError(
            "pilot-start consumption implementation is unavailable"
        )
    if getattr(
        implementation,
        "_production_pilot_start_consumption_boundary_installed",
        False,
    ):
        return

    def consume_pilot_start_authorization(
        *,
        authorization_proof: Any,
        preflight_signature: Any,
        authorization_signature: Any,
    ) -> Any:
        """Freshly verify the full upstream chain, then consume one signed nonce."""
        try:
            supplied = _snapshot_proof(authorization_proof)
            preflight_sig = _snapshot_signature(
                preflight_signature,
                name="ADR-DC-023 preflight",
            )
            authorization_sig = _snapshot_signature(
                authorization_signature,
                name="ADR-DC-024 authorization",
            )
        except PilotStartConsumptionProductionBoundaryError as exc:
            raise implementation.PilotStartConsumptionError(
                "pilot-start consumption authority inputs are invalid"
            ) from exc

        # A serialized ADR-DC-024 proof is not self-authenticating.  Invoke the
        # public ADR-DC-024 production facade so both the nested ADR-DC-023
        # signature and the human ADR-DC-024 signature are re-verified against
        # their canonical host-controlled verification keyrings.
        try:
            fresh = _start_auth.verify_pilot_start_authorization(
                preflight_proof=supplied.authorization.preflight_proof,
                authorization=supplied.authorization,
                signature=authorization_sig,
                preflight_signature=preflight_sig,
            )
            implementation.require_fresh_proof_identity(supplied, fresh)
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotStartConsumptionError(
                "fresh ADR-DC-024 authorization provenance verification failed"
            ) from exc

        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotStartConsumptionLedger(root)
            return implementation._consume_verified_pilot_start_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                preflight_signature_sha256=preflight_sig.sha256,
                ledger=ledger,
                now_provider=implementation._now_utc_seconds,
            )
        except (
            PilotStartConsumptionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotStartConsumptionError):
                raise
            raise implementation.PilotStartConsumptionError(
                "host-controlled pilot-start consumption failed closed"
            ) from exc

    implementation.consume_pilot_start_authorization = consume_pilot_start_authorization
    implementation._production_pilot_start_consumption_boundary_installed = True


__all__: list[str] = []
