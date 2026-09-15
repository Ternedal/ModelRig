"""Production host boundary for ADR-DC-047 exact local Git object materialization."""
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
    "rsi-pilot-exact-task-local-commit-object-write-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-object-write-ledger-v1"
)


class PilotExactTaskLocalCommitObjectWriteProductionBoundaryError(ValueError):
    """Production exact local Git object-write state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitObjectWriteProductionBoundaryError(
                "local-commit object-write ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitObjectWriteProductionBoundaryError(
            "canonical local-commit object-write ledger is not host-admin controlled"
        ) from exc


def _nondecreasing_clock(implementation: Any) -> Callable[[], str]:
    last = None
    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(value, name="production local-commit object-write clock")
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskLocalCommitObjectWriteError(
                "production local-commit object-write clock is invalid"
            ) from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskLocalCommitObjectWriteError(
                "system clock moved backwards during local-commit object write"
            )
        last = current
        return value
    return now


def install_pilot_exact_task_local_commit_object_write_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskLocalCommitObjectWriteProductionBoundaryError(
            "local-commit object-write implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_local_commit_object_write_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def materialize_pilot_exact_task_local_commit_objects(
        *,
        write_consumption_receipt: Any,
    ) -> Any:
        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskLocalCommitObjectWriteLedger(root)
            return implementation._materialize_verified_pilot_exact_task_local_commit_objects(
                write_consumption_receipt=write_consumption_receipt,
                ledger=ledger,
                now_provider=_nondecreasing_clock(implementation),
            )
        except (
            PilotExactTaskLocalCommitObjectWriteProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotExactTaskLocalCommitObjectWriteError):
                raise
            raise implementation.PilotExactTaskLocalCommitObjectWriteError(
                "host-controlled local-commit object write failed closed"
            ) from exc

    implementation.materialize_pilot_exact_task_local_commit_objects = (
        materialize_pilot_exact_task_local_commit_objects
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
