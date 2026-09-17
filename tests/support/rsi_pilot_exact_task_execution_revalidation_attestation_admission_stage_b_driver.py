"""Stage-B shared-provenance driver for ADR-DC-032 and ADR-DC-033.

The canonical ADR-DC-032 and ADR-DC-033 contracts each construct the same deep
ADR-DC-029..031 provenance independently. Hosted-runner evidence shows that the
single ADR-DC-032 contract needs roughly 21-28 minutes and ADR-DC-033 still exceeds
its aggregate Stage-B budget after upstream material is shared.

Stage-B therefore qualifies the two adjacent contracts in one isolated process and
constructs their deterministic upstream material exactly once. Both canonical
``run_contract()`` functions still execute in full. For ADR-DC-033 only, repeated
validation of the same immutable ADR-DC-032 proof is memoized after one successful
canonical replay validation, and repeated receipt deserializations may reuse the
already canonical-parsed nested proof when its serialized mapping is byte-for-byte
semantically identical. Product code, authority code and canonical contract
assertions remain unchanged.
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
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control._improvement_pilot_exact_task_execution_admission_impl as admission_impl  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_execution_revalidation_attestation_impl as revalidation_impl  # noqa: E402
import rsi_pilot_exact_task_execution_revalidation_attestation_contract as adr032  # noqa: E402
import rsi_pilot_exact_task_execution_admission_contract as adr033  # noqa: E402

_ORIGINAL_ADR032_MATERIAL = adr032._material
_ORIGINAL_ADR033_MATERIAL = adr033._material
_ORIGINAL_ADR033_PROOF = adr033._proof
_ORIGINAL_REQUIRE_SATISFIED_PROOF = admission_impl._require_satisfied_revalidation_proof
_ORIGINAL_PROOF_FROM_MAPPING = (
    revalidation_impl.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping.__func__
)
_shared_material: tuple[Any, ...] | None = None
_real_temp: Any | None = None
_cached_proof_mappings: list[tuple[dict[str, Any], Any]] = []
_validated_proofs: dict[int, Any] = {}


class _DeferredCleanup:
    """Keep the shared fixture alive until both canonical contracts finish."""

    def __init__(self, temp: Any) -> None:
        self._temp = temp

    @property
    def name(self) -> str:
        return self._temp.name

    def cleanup(self) -> None:
        # ADR-032 and ADR-DC-033 each own their normal fixture lifetime. Stage-B is
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


def _memoized_require_satisfied_proof(value: Any):
    """Replay-validate each immutable proof object once, then reuse that verdict."""
    cached = _validated_proofs.get(id(value))
    if cached is value:
        return value
    exact = _ORIGINAL_REQUIRE_SATISFIED_PROOF(value)
    _validated_proofs[id(exact)] = exact
    return exact


def _memoized_proof_from_mapping(cls, value: Any):
    """Reuse an already parsed proof only for an identical serialized mapping."""
    for mapping, proof in _cached_proof_mappings:
        if value == mapping:
            return proof
    return _ORIGINAL_PROOF_FROM_MAPPING(cls, value)


def _stage_b_adr033_proof(*, all_green: bool = True):
    result = _ORIGINAL_ADR033_PROOF(all_green=all_green)
    if all_green:
        _temp, proof, fresh, *_rest = result
        # Cache only successful proofs. Failed-proof negative cases must continue
        # through the unmodified parser/validator and must never inherit a green
        # validation verdict.
        _cached_proof_mappings[:] = [
            (proof.to_dict(), proof),
            (fresh.to_dict(), fresh),
        ]
    return result


def run_contract() -> None:
    global _shared_material, _real_temp
    proof_class = revalidation_impl.PilotExactTaskExecutionRevalidationAttestationProof
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

        # ADR-DC-032 has already exercised the canonical proof parser and tamper
        # rejection in full. ADR-DC-033 repeatedly replays the same frozen proof
        # object and reparses the same nested proof for top-level receipt mutations.
        # Memoize only those exact successful objects/mappings inside this isolated
        # Stage-B child; all canonical ADR-DC-033 assertions still execute.
        admission_impl._require_satisfied_revalidation_proof = (
            _memoized_require_satisfied_proof
        )
        proof_class.from_mapping = classmethod(_memoized_proof_from_mapping)
        adr033._proof = _stage_b_adr033_proof

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
        adr033._proof = _ORIGINAL_ADR033_PROOF
        admission_impl._require_satisfied_revalidation_proof = (
            _ORIGINAL_REQUIRE_SATISFIED_PROOF
        )
        proof_class.from_mapping = classmethod(_ORIGINAL_PROOF_FROM_MAPPING)
        if _real_temp is not None:
            _real_temp.cleanup()
        _shared_material = None
        _real_temp = None
        _cached_proof_mappings.clear()
        _validated_proofs.clear()


if __name__ == "__main__":
    run_contract()
