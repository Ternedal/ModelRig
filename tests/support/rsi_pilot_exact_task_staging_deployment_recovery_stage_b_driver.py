"""Stage-B driver for ADR-DC-075 with one shared live authorization chain.

The canonical ADR-DC-075 contract remains independently runnable. Stage-B reuses
only the immutable upstream authorization/provenance chain; every adversarial case
still gets a fresh transaction ledger and recovery ledger.
"""
from __future__ import annotations

import os

import rsi_pilot_exact_task_staging_deployment_recovery_contract as contract

_original_live_authorization = contract.tx_contract._live_authorization
_original_cleanup = contract._cleanup
_shared = None


def _live_authorization():
    global _shared
    if _shared is None:
        _shared = _original_live_authorization()
    return _shared


def _cleanup(items, auth_temp, tx_temp) -> None:
    if (
        _shared is not None
        and items is _shared[0]
        and auth_temp is _shared[5]
    ):
        tx_temp.cleanup()
        return
    _original_cleanup(items, auth_temp, tx_temp)


def run_contract() -> None:
    global _shared
    if os.name == "nt":
        return

    contract.tx_contract._live_authorization = _live_authorization
    contract._cleanup = _cleanup
    try:
        contract.run_contract()
    finally:
        if _shared is not None:
            _shared[5].cleanup()
            contract.state_contract.plan_contract.ready_contract._cleanup_source(
                _shared[0]
            )
            _shared = None
        contract.tx_contract._live_authorization = _original_live_authorization
        contract._cleanup = _original_cleanup


if __name__ == "__main__":
    run_contract()
