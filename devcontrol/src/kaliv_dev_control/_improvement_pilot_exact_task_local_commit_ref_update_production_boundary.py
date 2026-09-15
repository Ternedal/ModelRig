"""Production host boundary for ADR-DC-048 exact local branch ref update."""
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
    "rsi-pilot-exact-task-local-commit-ref-update-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-ref-update-ledger-v1"
)


class PilotExactTaskLocalCommitRefUpdateProductionBoundaryError(ValueError):
    """Production local-commit ref-update state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitRefUpdateProductionBoundaryError(
                "local-commit ref-update ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitRefUpdateProductionBoundaryError(
            "canonical local-commit ref-update ledger is not host-admin controlled"
        ) from exc


def _nondecreasing_clock(implementation: Any) -> Callable[[], str]:
    last = None

    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(
                value,
                name="production local-commit ref-update clock",
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskLocalCommitRefUpdateError(
                "production local-commit ref-update clock is invalid"
            ) from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskLocalCommitRefUpdateError(
                "system clock moved backwards during local-commit ref update"
            )
        last = current
        return value

    return now


def install_pilot_exact_task_local_commit_ref_update_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskLocalCommitRefUpdateProductionBoundaryError(
            "local-commit ref-update implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_local_commit_ref_update_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def attach_pilot_exact_task_local_commit(
        *,
        object_write_receipt: Any,
    ) -> Any:
        try:
            root = _canonical_ledger_root()
            ledger = implementation._PilotExactTaskLocalCommitRefUpdateLedger(root)
            return implementation._attach_verified_pilot_exact_task_local_commit(
                object_write_receipt=object_write_receipt,
                ledger=ledger,
                now_provider=_nondecreasing_clock(implementation),
            )
        except (
            PilotExactTaskLocalCommitRefUpdateProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(
                exc,
                implementation.PilotExactTaskLocalCommitRefUpdateError,
            ):
                raise
            raise implementation.PilotExactTaskLocalCommitRefUpdateError(
                "host-controlled local-commit ref update failed closed"
            ) from exc

    implementation.attach_pilot_exact_task_local_commit = (
        attach_pilot_exact_task_local_commit
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
