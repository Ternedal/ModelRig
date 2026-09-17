"""Stage-B shared-provenance driver for ADR-DC-032 and ADR-DC-033.

The canonical ADR-DC-032 and ADR-DC-033 contracts each construct the same deep
ADR-DC-029..031 provenance independently. Hosted-runner evidence shows that the
single ADR-DC-032 contract needs roughly 21-28 minutes and ADR-DC-033 still exceeds
its 1800s bound even after its duplicated failed-proof reconstruction is removed.

Stage-B therefore qualifies the two adjacent contracts in one isolated process and
constructs their deterministic upstream material exactly once. Both canonical
``run_contract()`` functions still execute in full. Only fixture construction and
lifetime are shared; product code, authority code and canonical contract assertions
remain unchanged.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import rsi_pilot_exact_task_execution_revalidation_attestation_contract as adr032  # noqa: E402
import rsi_pilot_exact_task_execution_admission_contract as adr033  # noqa: E402

_ORIGINAL_ADR032_MATERIAL = adr032._material
_ORIGINAL_ADR033_MATERIAL = adr033._material
_shared_material: tuple[Any, ...] | None = None
_real_temp: Any | None = None


class _DeferredCleanup:
    """Keep the shared fixture alive until both canonical contracts finish."""

    def __init__(self, temp: Any) -> None:
        self._temp = temp

    @property
    def name(self) -> str:
        return self._temp.name

    def cleanup(self) -> None:
        # ADR-032 and ADR-033 each own their normal fixture lifetime. Stage-B is
        # intentionally extending that lifetime across the adjacent pair, so their
        # individual cleanup calls are deferred to the driver-level finally block.
        return None


def _shared_material_provider() -> tuple[Any, ...]:
    global _shared_material, _real_temp
    if _shared_material is None:
        material_started = time.monotonic()
        print("Stage-B shared deep pair: START shared upstream material", flush=True)
        material = _ORIGINAL_ADR032_MATERIAL()
        _real_temp = material[0]
        _shared_material = (_DeferredCleanup(_real_temp), *material[1:])
        print(
            "Stage-B shared deep pair: PASS shared upstream material "
            f"({time.monotonic() - material_started:.1f}s)",
            flush=True,
        )
    return _shared_material


def run_contract() -> None:
    global _shared_material, _real_temp
    adr032._material = _shared_material_provider
    adr033._material = _shared_material_provider
    pair_started = time.monotonic()
    try:
        adr032_started = time.monotonic()
        print("Stage-B shared deep pair: START ADR-DC-032", flush=True)
        adr032.run_contract()
        print(
            f"Stage-B shared deep pair: PASS ADR-DC-032 ({time.monotonic() - adr032_started:.1f}s)",
            flush=True,
        )

        adr033_started = time.monotonic()
        print("Stage-B shared deep pair: START ADR-DC-033", flush=True)
        adr033.run_contract()
        print(
            f"Stage-B shared deep pair: PASS ADR-DC-033 ({time.monotonic() - adr033_started:.1f}s)",
            flush=True,
        )
        print(
            f"Stage-B shared deep pair: PASS aggregate ({time.monotonic() - pair_started:.1f}s)",
            flush=True,
        )
    finally:
        adr032._material = _ORIGINAL_ADR032_MATERIAL
        adr033._material = _ORIGINAL_ADR033_MATERIAL
        if _real_temp is not None:
            _real_temp.cleanup()
        _shared_material = None
        _real_temp = None


if __name__ == "__main__":
    run_contract()
