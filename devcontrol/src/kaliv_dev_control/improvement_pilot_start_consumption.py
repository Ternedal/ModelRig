"""Public host-pinned facade for ADR-DC-025 pilot-start consumption."""
from __future__ import annotations

from . import _improvement_pilot_start_consumption_impl as _implementation
from ._improvement_pilot_start_consumption_production_boundary import (
    install_pilot_start_consumption_production_boundary,
)

install_pilot_start_consumption_production_boundary(_implementation)

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    _implementation.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
)
PILOT_START_CONSUMPTION_AUTHORITY = _implementation.PILOT_START_CONSUMPTION_AUTHORITY
PILOT_START_CONSUMPTION_LEDGER_SCOPE = (
    _implementation.PILOT_START_CONSUMPTION_LEDGER_SCOPE
)
PilotStartConsumptionError = _implementation.PilotStartConsumptionError
PilotStartConsumptionReceipt = _implementation.PilotStartConsumptionReceipt
consume_pilot_start_authorization = _implementation.consume_pilot_start_authorization

# Deterministic test seams only. Production callers use the host-pinned function above.
_PilotStartConsumptionLedger = _implementation._PilotStartConsumptionLedger
_consume_verified_pilot_start_authorization = (
    _implementation._consume_verified_pilot_start_authorization
)
require_fresh_proof_identity = _implementation.require_fresh_proof_identity

__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_SCOPE",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "consume_pilot_start_authorization",
]

del install_pilot_start_consumption_production_boundary
