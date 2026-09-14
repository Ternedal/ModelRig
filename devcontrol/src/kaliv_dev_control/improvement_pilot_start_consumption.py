"""Public replay-safe ADR-DC-025 DC-L16 pilot-start consumption surface."""
from __future__ import annotations

from . import _improvement_pilot_start_consumption_impl as _implementation

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    _implementation.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
)
PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY = (
    _implementation.PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY
)
PILOT_START_CONSUMPTION_LEDGER_SCOPE = (
    _implementation.PILOT_START_CONSUMPTION_LEDGER_SCOPE
)
PilotStartConsumptionError = _implementation.PilotStartConsumptionError
PilotStartConsumptionReceipt = _implementation.PilotStartConsumptionReceipt
consume_pilot_start_authorization_once = (
    _implementation.consume_pilot_start_authorization_once
)

# Deterministic support-contract seams only. Production resolves the canonical
# elevated host-controlled replay ledger and freshly re-verifies ADR-023/024.
_consume_verified_pilot_start_authorization_once = (
    _implementation._consume_verified_pilot_start_authorization_once
)
_marker_path = _implementation._marker_path

__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_SCOPE",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "consume_pilot_start_authorization_once",
]
