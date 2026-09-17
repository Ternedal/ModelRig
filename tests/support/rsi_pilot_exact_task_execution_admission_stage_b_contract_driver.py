"""Stage-B-only optimized driver for ADR-DC-033 execution admission.

The canonical ADR-DC-033 contract intentionally constructs a complete ADR-DC-032
fixture for its positive path and then constructs the same deterministic upstream
fixture again for one signed negative revalidation case. Hosted Stage-B evidence
shows the second reconstruction pushes the isolated ADR-DC-033 process beyond its
1800s child bound even when no other deep contract is running.

This wrapper preserves the canonical contract and all of its assertions. It only
reuses the already-built upstream observation packet for the failed ADR-DC-032
case, while still building a fresh failed attestation, detached Ed25519 signature,
and verified failed proofs. Product code and the normal contract remain unchanged.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import rsi_pilot_exact_task_execution_admission_contract as contract  # noqa: E402

_ORIGINAL_PROOF = contract._proof
_cached_packet = None


def _stage_b_proof(*, all_green: bool = True):
    global _cached_packet

    if all_green:
        result = _ORIGINAL_PROOF(all_green=True)
        _temp, proof, _fresh, _signature, _human_signature, _admission_signature = result
        _cached_packet = proof.attestation.packet
        return result

    if _cached_packet is None:
        raise AssertionError("Stage-B ADR-DC-033 failed-proof reuse requires positive proof first")

    claim = contract._claim(_cached_packet, all_green=False)
    verifier, signature = contract._host_authority(claim)
    proof = contract.verify._verify_pilot_exact_task_execution_revalidation_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:36:00Z",
    )
    fresh = contract.verify._verify_pilot_exact_task_execution_revalidation_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:36:15Z",
    )

    # The canonical caller owns and cleans up a TemporaryDirectory returned by
    # _proof(). No upstream files are needed for this reused-packet negative case,
    # so provide an independent scratch lifetime with the same cleanup contract.
    temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-admission-stage-b-failed-")
    return temp, proof, fresh, signature, None, None


def run_contract() -> None:
    contract._proof = _stage_b_proof
    try:
        contract.run_contract()
    finally:
        contract._proof = _ORIGINAL_PROOF


if __name__ == "__main__":
    run_contract()
