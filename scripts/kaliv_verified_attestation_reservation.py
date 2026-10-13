"""Fail-closed coordinator primitive: verify signed bytes before durable replay reservation.

The caller must supply independent expected identities and independently owned
trust roots and database. This function NEVER approves a production release.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from kaliv_producer_attestation_envelope import (
    AttestationEnvelopeError, parse_envelope,
)
from kaliv_producer_signature_verifier import (
    AttestationVerificationError, verify_producer_attestation,
)
from kaliv_durable_attestation_replay_ledger import record_verified_attestation


def verify_and_reserve_attestation(
    raw: bytes,
    evidence: bytes,
    *,
    expected_release_id: str,
    expected_gate: str,
    expected_producer: str,
    expected_run_id: str,
    expected_repository_heads: Mapping[str, str],
    trusted_keys: Mapping[str, Mapping[str, bytes]],
    coordinator_database: str | Path,
) -> dict[str, object]:
    """Verify then atomically reserve once; no user-controlled verified flag.

    This closes the caller-supplied signature_verified boolean bypass in the
    integration path. It does not authenticate the caller or provision trust roots.
    """
    try:
        envelope = parse_envelope(raw)
    except AttestationEnvelopeError as exc:
        raise AttestationVerificationError("Malformed attestation") from exc
    if (not expected_producer or not expected_run_id
            or envelope["producer"] != expected_producer
            or envelope["run_id"] != expected_run_id):
        raise AttestationVerificationError("Independent producer/run mismatch")
    result = verify_producer_attestation(
        raw, evidence,
        expected_release_id=expected_release_id,
        expected_gate=expected_gate,
        expected_repository_heads=expected_repository_heads,
        trusted_keys=trusted_keys,
    )
    # The only True passed to the ledger is derived from an actual successful
    # cryptographic verification, not from caller-provided attestation JSON.
    record_verified_attestation(
        coordinator_database,
        release_id=expected_release_id,
        gate=expected_gate,
        producer=expected_producer,
        run_id=expected_run_id,
        evidence_sha256=envelope["evidence_sha256"],
        signature_verified=result["signature_valid"] is True,
    )
    return {
        **result,
        "producer_binding_valid": True,
        "run_binding_valid": True,
        "replay_durably_committed": True,
        "independent_provenance_verified": False,
        "human_approval_verified": False,
        "release_ready": False,
        "production_activation": False,
    }
