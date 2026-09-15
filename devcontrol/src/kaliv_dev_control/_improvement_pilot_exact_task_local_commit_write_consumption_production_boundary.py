"""Production host boundary for ADR-DC-046 local-commit write consumption."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-local-commit-write-consumption-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-write-consumption-ledger-v1"
)


class PilotExactTaskLocalCommitWriteConsumptionProductionBoundaryError(ValueError):
    """Production local-commit write-consumption state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitWriteConsumptionProductionBoundaryError(
                "local-commit write-consumption ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitWriteConsumptionProductionBoundaryError(
            "canonical local-commit write-consumption ledger is not host-admin controlled"
        ) from exc


def _nondecreasing_clock(implementation: Any) -> Callable[[], str]:
    last = None

    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(
                value, name="production local-commit write-consumption clock"
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskLocalCommitWriteConsumptionError(
                "production local-commit write-consumption clock is invalid"
            ) from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskLocalCommitWriteConsumptionError(
                "system clock moved backwards during local-commit write consumption"
            )
        last = current
        return value

    return now


def install_pilot_exact_task_local_commit_write_consumption_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskLocalCommitWriteConsumptionProductionBoundaryError(
            "local-commit write-consumption implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_local_commit_write_consumption_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def consume_pilot_exact_task_local_commit_authorization(
        *,
        admission_receipt: Any,
    ) -> Any:
        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskLocalCommitWriteConsumptionLedger(
                root
            )
            return implementation._consume_verified_pilot_exact_task_local_commit_authorization(
                admission_receipt=admission_receipt,
                ledger=ledger,
                now_provider=_nondecreasing_clock(implementation),
            )
        except (
            PilotExactTaskLocalCommitWriteConsumptionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(
                exc, implementation.PilotExactTaskLocalCommitWriteConsumptionError
            ):
                raise
            raise implementation.PilotExactTaskLocalCommitWriteConsumptionError(
                "host-controlled local-commit write consumption failed closed"
            ) from exc

    implementation.consume_pilot_exact_task_local_commit_authorization = (
        consume_pilot_exact_task_local_commit_authorization
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
