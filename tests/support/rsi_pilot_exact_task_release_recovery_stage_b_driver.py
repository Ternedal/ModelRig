"""Stage-B driver for ADR-DC-068 with one shared immutable release authority.

The canonical ADR-DC-068 contract remains independently runnable. Stage-B reuses
only the expensive immutable upstream release authority/provenance chain; every
adversarial case still creates fresh transaction and recovery ledgers.
"""
from __future__ import annotations

import os

import rsi_pilot_exact_task_release_recovery_contract as contract

_original_live_authority = contract._live_authority
_original_cleanup_case = contract._cleanup_case
_shared_raw = None
_shared_auth_temp = None


class _BorrowedTemp:
    def __init__(self, temp):
        self.name = temp.name

    def cleanup(self) -> None:
        return None


def _live_authority():
    global _shared_raw, _shared_auth_temp
    if _shared_raw is None:
        _shared_raw = _original_live_authority()
        _shared_auth_temp = _BorrowedTemp(_shared_raw[1])
    return (
        _shared_raw[0],
        _shared_auth_temp,
        _shared_raw[2],
        _shared_raw[3],
    )


def _cleanup_case(case) -> None:
    if _shared_raw is not None and case is _shared_raw[0]:
        return
    _original_cleanup_case(case)


def run_contract() -> None:
    global _shared_raw, _shared_auth_temp
    if os.name == "nt":
        return

    contract._live_authority = _live_authority
    contract._cleanup_case = _cleanup_case
    try:
        contract.run_contract()
    finally:
        if _shared_raw is not None:
            _shared_raw[1].cleanup()
            _original_cleanup_case(_shared_raw[0])
            _shared_raw = None
            _shared_auth_temp = None
        contract._live_authority = _original_live_authority
        contract._cleanup_case = _original_cleanup_case


if __name__ == "__main__":
    run_contract()
