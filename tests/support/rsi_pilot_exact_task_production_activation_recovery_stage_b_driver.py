"""Stage-B driver for ADR-DC-094 with shared normal readiness provenance.

The canonical recovery contract remains independently runnable. Stage-B reuses
only the expensive immutable ADR-DC-091 normal-readiness chain. Every recovery
case still creates a fresh ADR-DC-092 authorization, ADR-DC-093 transaction
ledger/filesystem, and ADR-DC-094 recovery ledger.
"""
from __future__ import annotations

import os

import rsi_pilot_exact_task_production_activation_recovery_contract as contract

_original_ready = contract.tx_contract._ready
_original_cleanup_ready = contract.tx_contract._cleanup_ready
_shared_normal = None


def _ready(recovered: bool):
    global _shared_normal
    if recovered:
        return _original_ready(True)
    if _shared_normal is None:
        _shared_normal = _original_ready(False)
    return _shared_normal


def _cleanup_ready(value) -> None:
    if _shared_normal is not None and value is _shared_normal[0]:
        return
    _original_cleanup_ready(value)


def run_contract() -> None:
    global _shared_normal
    if os.name == "nt":
        return

    contract.tx_contract._ready = _ready
    contract.tx_contract._cleanup_ready = _cleanup_ready
    try:
        contract.run_contract()
    finally:
        if _shared_normal is not None:
            _original_cleanup_ready(_shared_normal[0])
            _shared_normal = None
        contract.tx_contract._ready = _original_ready
        contract.tx_contract._cleanup_ready = _original_cleanup_ready


if __name__ == "__main__":
    run_contract()
