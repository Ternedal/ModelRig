"""Production host boundary for ADR-DC-025 pilot-start consumption."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_posix_host_control,
    _require_windows_host_control,
)
from .improvement_pilot_start_authorization import (
    PilotStartAuthorizationError,
    verify_pilot_start_authorization,
)

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-start-consumption-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-consumption-ledger-v1"
)


class PilotStartConsumptionProductionBoundaryError(ValueError):
    """Canonical host replay state for pilot-start consumption is unavailable."""


def _canonical_pilot_start_consumption_ledger_root() -> Path:
    if os.name == "posix":
        return _POSIX_LEDGER
    if os.name == "nt":
        return _WINDOWS_LEDGER
    raise PilotStartConsumptionProductionBoundaryError(
        "pilot-start consumption ledger is unsupported on this platform"
    )


def _host_controlled_pilot_start_consumption_root() -> Path:
    try:
        _require_elevated_operator()
        root = _canonical_pilot_start_consumption_ledger_root()
        if os.name == "posix":
            return _require_posix_host_control(root)
        if os.name == "nt":
            return _require_windows_host_control(root)
    except PhysicalHostStateError as exc:
        raise PilotStartConsumptionProductionBoundaryError(
            "pilot-start consumption requires a pre-provisioned host-admin ledger"
        ) from exc
    raise PilotStartConsumptionProductionBoundaryError(
        "pilot-start consumption host-control validation is unavailable"
    )


def _same_authorization_identity(left: Any, right: Any) -> bool:
    for field in (
        "authorization_sha256",
        "signature_sha256",
        "key_id",
        "issuer_actor_id",
        "issuer_system_id",
        "preflight_proof_sha256",
        "attestation_sha256",
        "packet_sha256",
        "selection_proof_sha256",
        "candidate_proof_sha256",
        "requirements_sha256",
        "trial_scope_sha256",
        "start_nonce_sha256",
        "one_shot_start_required",
        "start_consumed",
        "integration_ready",
        "pilot_start_authorized",
        "product_pilot_started",
        "local_commit_authorized",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
        "authority",
    ):
        if getattr(left, field, object()) != getattr(right, field, object()):
            return False
    return left.authorization.to_dict() == right.authorization.to_dict()


def install_pilot_start_consumption_production_boundary(implementation: Any) -> None:
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

    private_consume = implementation._consume_pilot_start_authorization

    def consume_pilot_start_authorization(
        *,
        proof: Any,
        signature: Any,
        preflight_signature: Any,
        ledger: Any = None,
    ) -> Any:
        if ledger is not None:
            raise implementation.PilotStartConsumptionError(
                "caller-selected pilot-start consumption ledger is not production authority"
            )
        try:
            presented = implementation._require_authorized_proof(proof)
            # A serialized proof is evidence, not live authority. Re-verify the
            # ADR-DC-024 human signature and ADR-DC-023 detached signature at
            # consumption time through their host-pinned production facades.
            fresh = verify_pilot_start_authorization(
                preflight_proof=presented.authorization.preflight_proof,
                authorization=presented.authorization,
                signature=signature,
                preflight_signature=preflight_signature,
            )
        except (PilotStartAuthorizationError, ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotStartConsumptionError(
                "fresh ADR-DC-024 authorization provenance verification failed"
            ) from exc
        if getattr(signature, "sha256", None) != presented.signature_sha256:
            raise implementation.PilotStartConsumptionError(
                "detached ADR-DC-024 signature does not match presented proof"
            )
        if not _same_authorization_identity(presented, fresh):
            raise implementation.PilotStartConsumptionError(
                "fresh ADR-DC-024 authorization identity does not match presented proof"
            )
        try:
            root = _host_controlled_pilot_start_consumption_root()
            host_ledger = implementation.PilotStartConsumptionLedger(
                root=root,
                ledger_id=implementation.PILOT_START_CONSUMPTION_LEDGER_ID,
            )
        except (PilotStartConsumptionProductionBoundaryError, ValueError) as exc:
            raise implementation.PilotStartConsumptionError(
                "host-controlled pilot-start consumption replay state is unavailable"
            ) from exc
        return private_consume(
            proof=fresh,
            ledger=host_ledger,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.consume_pilot_start_authorization = consume_pilot_start_authorization
    implementation._production_pilot_start_consumption_boundary_installed = True


__all__: list[str] = []
