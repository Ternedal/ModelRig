"""Shared-provenance Stage-B driver for ADR-DC-098 through ADR-DC-100.

The canonical contracts remain independently runnable and unchanged in authority
semantics. This Stage-B-only driver builds their expensive immutable upstream
fixture once, keeps it live while all three full adversarial contracts execute,
and cleans it up only after all finish.
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


def run_contract() -> None:
    if os.name == "nt":
        return

    started = time.monotonic()
    fixture = lineage_contract._build_fixture()
    built = time.monotonic()
    print(
        f"ADR-DC-098/099/100 shared provenance built in {built - started:.1f}s",
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
    finally:
        lineage_contract._cleanup(fixture)


if __name__ == "__main__":
    run_contract()
