"""Production host boundary for ADR-DC-053 remote-publication write consumption."""
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
    "rsi-pilot-exact-task-remote-publication-write-consumption-ledger-v1"
)
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state"
    r"\rsi-pilot-exact-task-remote-publication-write-consumption-ledger-v1"
)


class PilotExactTaskRemotePublicationWriteConsumptionProductionBoundaryError(
    ValueError
):
    """Production ADR-DC-053 host state is unsafe or unavailable."""


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskRemotePublicationWriteConsumptionProductionBoundaryError(
                "remote-publication write-consumption ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationWriteConsumptionProductionBoundaryError(
            "canonical remote-publication write-consumption ledger is not host-admin controlled"
        ) from exc


def _nondecreasing_consumption_clock(implementation: Any) -> Callable[[], str]:
    last = None

    def now() -> str:
        nonlocal last
        value = implementation._now_utc_seconds()
        try:
            current = implementation._utc(
                value,
                name="production remote-publication write-consumption clock",
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise implementation.PilotExactTaskRemotePublicationWriteConsumptionError(
                "production remote-publication write-consumption clock is invalid"
            ) from exc
        if last is not None and current < last:
            raise implementation.PilotExactTaskRemotePublicationWriteConsumptionError(
                "system clock moved backwards during remote-publication write consumption"
            )
        last = current
        return value

    return now


def install_pilot_exact_task_remote_publication_write_consumption_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskRemotePublicationWriteConsumptionProductionBoundaryError(
            "remote-publication write-consumption implementation is unavailable"
        )
    marker = (
        "_production_pilot_exact_task_remote_publication_write_consumption_boundary_installed"
    )
    if getattr(implementation, marker, False):
        return

    def consume_pilot_exact_task_remote_publication_authorization(
        authorization_admission_receipt: Any,
    ) -> Any:
        try:
            root = _canonical_ledger_root()
            ledger = (
                implementation._PilotExactTaskRemotePublicationWriteConsumptionLedger(
                    root
                )
            )
            return implementation._consume_verified_pilot_exact_task_remote_publication_authorization(
                authorization_admission_receipt=authorization_admission_receipt,
                ledger=ledger,
                now_provider=_nondecreasing_consumption_clock(implementation),
            )
        except (
            PilotExactTaskRemotePublicationWriteConsumptionProductionBoundaryError,
            PhysicalHostStateError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(
                exc,
                implementation.PilotExactTaskRemotePublicationWriteConsumptionError,
            ):
                raise
            raise implementation.PilotExactTaskRemotePublicationWriteConsumptionError(
                "host-controlled remote-publication write consumption failed closed"
            ) from exc

    implementation.consume_pilot_exact_task_remote_publication_authorization = (
        consume_pilot_exact_task_remote_publication_authorization
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
