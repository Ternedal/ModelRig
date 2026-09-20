"""Stage-B driver for ADR-DC-093 with shared normal readiness provenance.

This preserves the ADR-DC-093 contract unchanged while avoiding repeated rebuilds
of the same expensive live normal-readiness chain for each isolated adversarial
case. Each case still creates fresh ADR-DC-092 authorization and ADR-DC-093
transaction ledgers/filesystems. The recovered-path fixture remains fresh and
independent.
"""
from __future__ import annotations

import rsi_pilot_exact_task_production_activation_transaction_contract as contract

_original_ready = contract._ready
_original_cleanup_ready = contract._cleanup_ready
_shared_normal = None


def _ready(recovered: bool):
    global _shared_normal
    if recovered:
        return _original_ready(True)
    if _shared_normal is None:
        _shared_normal = _original_ready(False)
    return _shared_normal


def _cleanup_ready(value) -> None:
    if value is _shared_normal:
        return
    _original_cleanup_ready(value)


def run_contract() -> None:
    global _shared_normal
    contract._ready = _ready
    contract._cleanup_ready = _cleanup_ready
    try:
        contract.run_contract()
    finally:
        if _shared_normal is not None:
            _original_cleanup_ready(_shared_normal)
            _shared_normal = None
        contract._ready = _original_ready
        contract._cleanup_ready = _original_cleanup_ready


if __name__ == "__main__":
    run_contract()
