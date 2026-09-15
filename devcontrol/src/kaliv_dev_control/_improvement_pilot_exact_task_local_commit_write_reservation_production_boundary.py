"""Host-pinned production boundary for ADR-DC-045 local-write reservation."""
from __future__ import annotations

from typing import Any

from . import improvement_pilot_exact_task_local_commit_authorization as authorization_boundary


class PilotExactTaskLocalCommitWriteReservationProductionBoundaryError(ValueError):
    """Production local-write reservation authority is unsafe or unavailable."""


def install_pilot_exact_task_local_commit_write_reservation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskLocalCommitWriteReservationProductionBoundaryError(
            "local-write reservation implementation is unavailable"
        )
    if getattr(
        implementation,
        "_production_pilot_exact_task_local_commit_write_reservation_boundary_installed",
        False,
    ):
        return

    private_reserve = implementation._reserve_verified_exact_task_local_commit_write

    def reserve_pilot_exact_task_local_commit_write(
        *,
        authorization_proof: Any,
        authorization_signature: Any,
        local_commit_object_identity: Any,
    ) -> Any:
        try:
            supplied = implementation._require_authorization_proof(authorization_proof)
            fresh = authorization_boundary.verify_pilot_exact_task_local_commit_authorization(
                local_commit_write_requirements=(
                    supplied.authorization.local_commit_write_requirements
                ),
                authorization=supplied.authorization,
                signature=authorization_signature,
            )
            implementation.require_fresh_authorization_proof_identity(
                supplied,
                fresh,
            )
        except Exception as exc:
            raise implementation.PilotExactTaskLocalCommitWriteReservationError(
                "fresh host-controlled ADR-DC-044 signature verification failed"
            ) from exc
        try:
            root = implementation._canonical_ledger_root()
            ledger = implementation._PilotExactTaskLocalCommitWriteReservationLedger(root)
            return private_reserve(
                authorization_proof=fresh,
                local_commit_object_identity=local_commit_object_identity,
                ledger=ledger,
                now_provider=implementation._now_utc_seconds,
            )
        except implementation.PilotExactTaskLocalCommitWriteReservationError:
            raise
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            raise implementation.PilotExactTaskLocalCommitWriteReservationError(
                "host-controlled local-write reservation failed closed"
            ) from exc

    implementation.reserve_pilot_exact_task_local_commit_write = (
        reserve_pilot_exact_task_local_commit_write
    )
    implementation._production_pilot_exact_task_local_commit_write_reservation_boundary_installed = True


__all__: list[str] = []
