"""Locked Stage-B wrapper for ADR-DC-067 followed by ADR-DC-068."""
from __future__ import annotations

from rsi_pilot_exact_task_release_transaction_contract_base import (
    _ledger,
    _live_authority,
    run_contract as run_release_transaction_contract,
)


def run_contract() -> None:
    run_release_transaction_contract()
    from rsi_pilot_exact_task_release_recovery_contract import (
        run_contract as run_release_recovery_contract,
    )

    run_release_recovery_contract()


if __name__ == "__main__":
    run_contract()
