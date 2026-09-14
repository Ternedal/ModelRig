"""Public host-pinned facade for ADR-DC-025 one-shot pilot-start consumption."""
from __future__ import annotations

from . import _improvement_pilot_start_consumption_impl as _implementation
from ._improvement_pilot_start_consumption_production_boundary import (
    install_pilot_start_consumption_production_boundary,
)

install_pilot_start_consumption_production_boundary(_implementation)

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    _implementation.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
)
PILOT_START_CONSUMPTION_RESERVATION_SCHEMA = (
    _implementation.PILOT_START_CONSUMPTION_RESERVATION_SCHEMA
)
PILOT_START_CONSUMPTION_AUTHORITY = _implementation.PILOT_START_CONSUMPTION_AUTHORITY
PILOT_START_CONSUMPTION_LEDGER_ID = _implementation.PILOT_START_CONSUMPTION_LEDGER_ID
PilotStartConsumptionError = _implementation.PilotStartConsumptionError
PilotStartConsumptionReceipt = _implementation.PilotStartConsumptionReceipt
consume_pilot_start_authorization = _implementation.consume_pilot_start_authorization

# Deterministic test seam only; production consumption is host-pinned above.
PilotStartConsumptionLedger = _implementation.PilotStartConsumptionLedger
_consume_pilot_start_authorization = _implementation._consume_pilot_start_authorization

__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_RESERVATION_SCHEMA",
    "PILOT_START_CONSUMPTION_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_ID",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "consume_pilot_start_authorization",
]

del install_pilot_start_consumption_production_boundary
