"""Stage-B driver for ADR-DC-081 with shared normal/recovered authorization chains.

The canonical ADR-DC-081 contract remains independently runnable. Stage-B reuses
only immutable upstream authorization/provenance; each adversarial case still
creates fresh transaction and recovery ledgers.
"""
from __future__ import annotations

import os

import rsi_pilot_exact_task_staging_deployment_status_recovery_contract as contract

_original_authorization = contract.tx_contract._authorization
_original_cleanup = contract._cleanup
_shared = {}


def _authorization(*, recovered=False):
    key = bool(recovered)
    if key not in _shared:
        _shared[key] = _original_authorization(recovered=recovered)
    return _shared[key]


def _cleanup(context, auth_temp, tx_temp) -> None:
    for value in _shared.values():
        if context is value[0] and auth_temp is value[3]:
            tx_temp.cleanup()
            return
    _original_cleanup(context, auth_temp, tx_temp)


def run_contract() -> None:
    if os.name == "nt":
        return

    contract.tx_contract._authorization = _authorization
    contract._cleanup = _cleanup
    try:
        contract.run_contract()
    finally:
        for value in _shared.values():
            value[3].cleanup()
            contract.state_contract._cleanup(value[0])
        _shared.clear()
        contract.tx_contract._authorization = _original_authorization
        contract._cleanup = _original_cleanup


if __name__ == "__main__":
    run_contract()
