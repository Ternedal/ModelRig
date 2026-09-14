"""Regression for fresh ADR-DC-023 provenance before ADR-DC-024 authority."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control.improvement_pilot_runtime_preflight_attestation as attestation  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_authorization as start_auth  # noqa: E402
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_start_authorization_production_boundary as boundary,
)
from rsi_pilot_runtime_preflight_attestation_proof_contract import (  # noqa: E402
    _authority as _preflight_authority,
    _claim as _preflight_claim,
)


def _proof_signature_verifier():
    claim = _preflight_claim(all_green=True)
    verifier, signature = _preflight_authority(claim)
    proof = attestation._verify_pilot_runtime_preflight_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:24:00Z",
    )
    return proof, signature, verifier


def _reject(fragment: str, fn) -> None:
    try:
        fn()
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
        return
    raise AssertionError(f"ADR-DC-024 provenance unexpectedly accepted: {fragment}")


def run_contract() -> None:
    proof, signature, verifier = _proof_signature_verifier()

    boundary._verify_preflight_provenance(
        preflight_proof=proof,
        preflight_signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:26:00Z",
    )

    # ADR-DC-023 proof objects are replay-validated structures, not self-
    # authenticating signatures.  A caller can construct a structurally valid
    # proof-shaped object with altered signature metadata; ADR-DC-024 production
    # must not trust that object without the detached signature and host keyring.
    forged_signature_hash = replace(proof, signature_sha256="f" * 64)
    assert attestation.PilotRuntimePreflightAttestationProof.from_mapping(
        forged_signature_hash.to_dict()
    ) == forged_signature_hash
    _reject(
        "detached signature does not match supplied preflight proof",
        lambda: boundary._verify_preflight_provenance(
            preflight_proof=forged_signature_hash,
            preflight_signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        ),
    )

    forged_key_id = replace(proof, key_id="forged-preflight-key")
    _reject(
        "fresh provenance mismatch: key_id",
        lambda: boundary._verify_preflight_provenance(
            preflight_proof=forged_key_id,
            preflight_signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        ),
    )

    bad_signature = replace(signature, signature_hex="0" * 128)
    _reject(
        "provenance verification failed",
        lambda: boundary._verify_preflight_provenance(
            preflight_proof=proof,
            preflight_signature=bad_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        ),
    )

    _reject(
        "detached ADR-DC-023 preflight signature is required",
        lambda: start_auth.verify_pilot_start_authorization(
            preflight_proof=proof,
            authorization=None,
            signature=None,
        ),
    )


if __name__ == "__main__":
    run_contract()
