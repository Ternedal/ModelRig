"""Stage-B driver for ADR-DC-074 with one shared immutable authorization chain.

The canonical ADR-DC-074 contract remains independently runnable. Stage-B reuses
only the expensive immutable upstream authorization/provenance chain; each
adversarial case still creates a fresh transaction ledger and transport/writer.
"""
from __future__ import annotations

import os

import rsi_pilot_exact_task_staging_deployment_transaction_contract as contract

_original_live_authorization = contract._live_authorization
_original_cleanup_source = (
    contract.state_contract.plan_contract.ready_contract._cleanup_source
)
_shared_raw = None
_shared_auth_temp = None


class _BorrowedTemp:
    def __init__(self, temp):
        self.name = temp.name

    def cleanup(self) -> None:
        return None


def _live_authorization():
    global _shared_raw, _shared_auth_temp
    if _shared_raw is None:
        _shared_raw = _original_live_authorization()
        _shared_auth_temp = _BorrowedTemp(_shared_raw[5])
    return (
        _shared_raw[0],
        _shared_raw[1],
        _shared_raw[2],
        _shared_raw[3],
        _shared_raw[4],
        _shared_auth_temp,
    )


def _cleanup_source(items) -> None:
    if _shared_raw is not None and items is _shared_raw[0]:
        return
    _original_cleanup_source(items)


def run_contract() -> None:
    global _shared_raw, _shared_auth_temp
    if os.name == "nt":
        return

    contract._live_authorization = _live_authorization
    contract.state_contract.plan_contract.ready_contract._cleanup_source = (
        _cleanup_source
    )
    try:
        contract.run_contract()
    finally:
        if _shared_raw is not None:
            _shared_raw[5].cleanup()
            _original_cleanup_source(_shared_raw[0])
            _shared_raw = None
            _shared_auth_temp = None
        contract._live_authorization = _original_live_authorization
        contract.state_contract.plan_contract.ready_contract._cleanup_source = (
            _original_cleanup_source
        )


if __name__ == "__main__":
    run_contract()
