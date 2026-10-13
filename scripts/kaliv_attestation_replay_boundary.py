"""Non-authorizing attestation replay and producer-binding check.

Replay records and expected producer/run must be supplied by an independent
coordinator. This module does not persist a replay ledger or approve releases.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping

from kaliv_producer_attestation_envelope import (
    AttestationEnvelopeError, parse_envelope,
)
from kaliv_producer_signature_verifier import (
    AttestationVerificationError, verify_producer_attestation,
)


def verify_attestation_with_replay_boundary(
    raw: bytes,
    evidence: bytes,
    *,
    expected_release_id: str,
    expected_gate: str,
    expected_producer: str,
    expected_run_id: str,
    expected_repository_heads: Mapping[str, str],
    trusted_keys: Mapping[str, Mapping[str, bytes]],
    previously_accepted: Collection[tuple[str, str, str, str]],
) -> dict[str, object]:
    """Verify independently expected producer/run and reject known replay IDs.

    The coordinator MUST atomically record accepted (release, gate, producer,
    run) tuples in a durable, independently controlled store. Without that
    atomic commit, this is only a best-effort preflight check.
    """
    if not expected_producer or not expected_run_id:
        raise AttestationVerificationError("Missing independently expected producer/run")
    try:
        envelope = parse_envelope(raw)
    except AttestationEnvelopeError as exc:
        raise AttestationVerificationError("Malformed attestation") from exc
    if envelope["producer"] != expected_producer or envelope["run_id"] != expected_run_id:
        raise AttestationVerificationError("Producer/run binding mismatch")
    identity = (expected_release_id, expected_gate, expected_producer, expected_run_id)
    if identity in previously_accepted:
        raise AttestationVerificationError("Previously accepted attestation identity")
    result = verify_producer_attestation(
        raw, evidence,
        expected_release_id=expected_release_id,
        expected_gate=expected_gate,
        expected_repository_heads=expected_repository_heads,
        trusted_keys=trusted_keys,
    )
    return {
        **result,
        "producer_binding_valid": True,
        "run_binding_valid": True,
        "replay_preflight_passed": True,
        "replay_durably_committed": False,
        "independent_provenance_verified": False,
        "release_ready": False,
        "production_activation": False,
    }
