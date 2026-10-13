"""Strict, non-authorizing parsing of V1 producer attestation envelopes.

This module does not verify signatures or confer release authority.
Trust anchors must be supplied by a separate independently controlled verifier.
"""
from __future__ import annotations

import json
import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED = frozenset({
    "schema", "release_id", "gate", "producer", "run_id",
    "evidence_sha256", "repository_heads", "signature",
})
_REPOS = frozenset({"ModelRig", "BodyRig", "VisionRig", "VoiceRig"})
_SIG = frozenset({"algorithm", "key_id", "value"})


class AttestationEnvelopeError(ValueError):
    """An envelope is malformed or ambiguous."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AttestationEnvelopeError("Duplicate JSON key")
        result[key] = value
    return result


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or value.strip() != value:
        raise AttestationEnvelopeError(f"Invalid {label}")
    return value


def parse_envelope(raw: bytes, *, max_bytes: int = 16384) -> dict[str, Any]:
    """Reject ambiguous or unbounded inputs; return an untrusted envelope.

    Parsing success NEVER means signature, provenance, or release approval.
    """
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise AttestationEnvelopeError("Invalid envelope size")
    try:
        envelope = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(AttestationEnvelopeError("Nonfinite number")),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AttestationEnvelopeError("Invalid JSON envelope") from exc
    if type(envelope) is not dict or set(envelope) != _ALLOWED:
        raise AttestationEnvelopeError("Invalid envelope fields")
    if envelope["schema"] != "kaliv-producer-attestation/v1":
        raise AttestationEnvelopeError("Unknown schema")
    for key in ("release_id", "gate", "producer", "run_id"):
        _nonempty(envelope[key], key)
    if not isinstance(envelope["evidence_sha256"], str) or not _SHA256.fullmatch(envelope["evidence_sha256"]):
        raise AttestationEnvelopeError("Invalid evidence digest")
    heads = envelope["repository_heads"]
    if type(heads) is not dict or set(heads) != _REPOS:
        raise AttestationEnvelopeError("Invalid repository heads")
    if any(not isinstance(v, str) or not _SHA256.fullmatch(v) for v in heads.values()):
        raise AttestationEnvelopeError("Invalid repository SHA")
    signature = envelope["signature"]
    if type(signature) is not dict or set(signature) != _SIG:
        raise AttestationEnvelopeError("Invalid signature fields")
    if signature["algorithm"] != "Ed25519":
        raise AttestationEnvelopeError("Unsupported signature algorithm")
    for key in ("key_id", "value"):
        _nonempty(signature[key], key)
    return envelope


def canonical_signed_payload(envelope: dict[str, Any]) -> bytes:
    """Produce deterministic payload bytes excluding the untrusted signature.

    Only call after parse_envelope; a separate trusted verifier must verify
    the signature and bind key_id to an independent gate-specific trust root.
    """
    return json.dumps(
        {key: envelope[key] for key in sorted(_ALLOWED - {"signature"})},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
