"""Shared-provenance Stage-B driver for ADR-DC-098 through execution admission.

The canonical contracts remain independently runnable and unchanged in authority
semantics. This Stage-B-only driver builds their expensive immutable upstream
fixture once, keeps it live while the full ADR-DC-098/099/100, repaired
start-readiness, start transaction/recovery and execution-admission contracts
execute, then cleans up.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_task_registry_contract as registry_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_runtime_preflight_contract as runtime_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_readiness_contract as readiness_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_authorization_contract as authorization_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_transaction_contract as start_transaction_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_recovery_contract as start_recovery_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_execution_admission_contract as execution_admission_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as product_capability_contract  # noqa: E402


def run_contract() -> None:
    if os.name == "nt":
        return

    started = time.monotonic()
    fixture = lineage_contract._build_fixture()
    built = time.monotonic()
    print(
        f"product-pilot tail shared provenance built in {built - started:.1f}s",
        flush=True,
    )
    try:
        lineage_contract.run_contract(shared_fixture=fixture)
        lineage_done = time.monotonic()
        print(
            f"ADR-DC-098 canonical contract completed in {lineage_done - built:.1f}s",
            flush=True,
        )
        registry_contract.run_contract(shared_fixture=fixture)
        registry_done = time.monotonic()
        print(
            f"ADR-DC-099 canonical contract completed in {registry_done - lineage_done:.1f}s",
            flush=True,
        )
        runtime_contract.run_contract(shared_fixture=fixture)
        runtime_done = time.monotonic()
        print(
            f"ADR-DC-100 canonical contract completed in {runtime_done - registry_done:.1f}s",
            flush=True,
        )
        readiness_contract.run_contract(shared_fixture=fixture)
        readiness_done = time.monotonic()
        print(
            f"readiness-v2 canonical contract completed in {readiness_done - runtime_done:.1f}s",
            flush=True,
        )
        authorization_contract.run_contract(shared_fixture=fixture)
        authorization_done = time.monotonic()
        print(
            f"ADR-DC-097 authorization contract completed in {authorization_done - readiness_done:.1f}s",
            flush=True,
        )
        start_transaction_contract.run_contract(shared_fixture=fixture)
        transaction_done = time.monotonic()
        print(
            f"ADR-DC-102 start-transaction contract completed in {transaction_done - authorization_done:.1f}s",
            flush=True,
        )
        start_recovery_contract.run_contract(shared_fixture=fixture)
        recovery_done = time.monotonic()
        print(
            f"ADR-DC-103 start-recovery contract completed in {recovery_done - transaction_done:.1f}s",
            flush=True,
        )
        execution_admission_contract.run_contract(shared_fixture=fixture)
        admission_done = time.monotonic()
        print(
            f"ADR-DC-104 execution-admission contract completed in {admission_done - recovery_done:.1f}s",
            flush=True,
        )
        product_capability_contract.run_contract(shared_fixture=fixture)
        capability_done = time.monotonic()
        print(
            f"ADR-DC-105 product-capability contract completed in {capability_done - admission_done:.1f}s",
            flush=True,
        )
    finally:
        lineage_contract._cleanup(fixture)


if __name__ == "__main__":
    run_contract()
