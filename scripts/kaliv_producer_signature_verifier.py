"""Verify producer signatures against independently pinned, gate-scoped Ed25519 keys.

A successful signature check is NOT release approval or physical provenance proof.
The trusted_keys mapping MUST originate outside the attestation/evidence bundle.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping

from kaliv_producer_attestation_envelope import (
    AttestationEnvelopeError, canonical_signed_payload, parse_envelope,
)


class AttestationVerificationError(ValueError):
    """Signature, binding, or trust-policy verification failed."""


def _decode_exact(value: str, expected: int) -> bytes:
    if not isinstance(value, str):
        raise AttestationVerificationError("Invalid base64 type")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AttestationVerificationError("Invalid base64") from exc
    if len(decoded) != expected or base64.b64encode(decoded).decode("ascii") != value:
        raise AttestationVerificationError("Invalid encoded length or noncanonical base64")
    return decoded


def verify_producer_attestation(
    raw: bytes,
    evidence: bytes,
    *,
    expected_release_id: str,
    expected_gate: str,
    expected_repository_heads: Mapping[str, str],
    trusted_keys: Mapping[str, Mapping[str, bytes]],
) -> dict[str, object]:
    """Verify signature and bytes against caller-pinned independent trust roots.

    Returns only signature_valid/evidence_digest_valid. Never release_ready.
    This is a primitive, not an authorization decision; policy, replay protection,
    producer identity, approvals and independently obtained artifacts remain separate.
    """
    try:
        envelope = parse_envelope(raw)
    except AttestationEnvelopeError as exc:
        raise AttestationVerificationError("Malformed attestation") from exc
    if envelope["release_id"] != expected_release_id or envelope["gate"] != expected_gate:
        raise AttestationVerificationError("Release/gate binding mismatch")
    if envelope["repository_heads"] != dict(expected_repository_heads):
        raise AttestationVerificationError("Repository head mismatch")
    if not isinstance(evidence, bytes):
        raise AttestationVerificationError("Evidence must be bytes")
    actual_digest = hashlib.sha256(evidence).hexdigest()
    if not hmac.compare_digest(actual_digest, envelope["evidence_sha256"]):
        raise AttestationVerificationError("Evidence digest mismatch")
    signature = envelope["signature"]
    gate_keys = trusted_keys.get(expected_gate)
    if not isinstance(gate_keys, Mapping):
        raise AttestationVerificationError("No independently trusted gate keys")
    public_key_bytes = gate_keys.get(signature["key_id"])
    if not isinstance(public_key_bytes, bytes) or len(public_key_bytes) != 32:
        raise AttestationVerificationError("Untrusted signer key")
    signature_bytes = _decode_exact(signature["value"], 64)
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise AttestationVerificationError("Ed25519 verification backend unavailable") from exc
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes, canonical_signed_payload(envelope)
        )
    except (InvalidSignature, ValueError) as exc:
        raise AttestationVerificationError("Signature verification failed") from exc
    return {
        "schema": "kaliv-producer-signature-check/v1",
        "release_id": expected_release_id,
        "gate": expected_gate,
        "signature_valid": True,
        "evidence_digest_valid": True,
        "independent_provenance_verified": False,
        "human_approval_verified": False,
        "release_ready": False,
        "production_activation": False,
    }
