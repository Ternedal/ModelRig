"""Public host-pinned facade for ADR-DC-053 remote-publication write consumption."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_remote_publication_write_consumption_impl as _implementation
from ._improvement_pilot_exact_task_remote_publication_write_consumption_production_boundary import (
    install_pilot_exact_task_remote_publication_write_consumption_production_boundary,
)

install_pilot_exact_task_remote_publication_write_consumption_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE
)
PilotExactTaskRemotePublicationWriteConsumptionError = (
    _implementation.PilotExactTaskRemotePublicationWriteConsumptionError
)
PilotExactTaskRemotePublicationWriteConsumptionReceipt = (
    _implementation.PilotExactTaskRemotePublicationWriteConsumptionReceipt
)
consume_pilot_exact_task_remote_publication_authorization = (
    _implementation.consume_pilot_exact_task_remote_publication_authorization
)

# Deterministic test seam only; production uses the host-controlled ledger above.
_PilotExactTaskRemotePublicationWriteConsumptionLedger = (
    _implementation._PilotExactTaskRemotePublicationWriteConsumptionLedger
)
_consume_verified_pilot_exact_task_remote_publication_authorization = (
    _implementation._consume_verified_pilot_exact_task_remote_publication_authorization
)
_get_live_remote_publication_write_consumption_inputs = (
    _implementation._get_live_remote_publication_write_consumption_inputs
)

__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE",
    "PilotExactTaskRemotePublicationWriteConsumptionError",
    "PilotExactTaskRemotePublicationWriteConsumptionReceipt",
    "consume_pilot_exact_task_remote_publication_authorization",
]

del install_pilot_exact_task_remote_publication_write_consumption_production_boundary
