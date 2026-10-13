"""Strict coordinator policy parser; policy bytes must be provisioned independently.

This is a non-authorizing trust-root loader. It deliberately refuses to load
policy from an attestation bundle, repository file, or producer-provided URL.
"""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Any

from kaliv_producer_attestation_envelope import _unique_pairs


class CoordinatorPolicyError(ValueError):
    """Untrusted or malformed coordinator policy."""


_ALLOWED = {"schema", "release_id", "repository_heads", "gate_keys"}
_REPOS = {"ModelRig", "BodyRig", "VisionRig", "VoiceRig"}


def parse_coordinator_policy(raw: bytes) -> dict[str, Any]:
    """Validate independently delivered policy bytes; never grant release."""
    if type(raw) is not bytes or len(raw) > 32768:
        raise CoordinatorPolicyError("Invalid policy byte length")
    try:
        policy = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CoordinatorPolicyError("Invalid policy JSON") from exc
    if type(policy) is not dict or set(policy) != _ALLOWED:
        raise CoordinatorPolicyError("Unexpected policy fields")
    if policy["schema"] != "kaliv-independent-coordinator-policy/v1":
        raise CoordinatorPolicyError("Unknown policy schema")
    if type(policy["release_id"]) is not str or not 0 < len(policy["release_id"]) <= 256:
        raise CoordinatorPolicyError("Invalid release ID")
    heads = policy["repository_heads"]
    if type(heads) is not dict or set(heads) != _REPOS:
        raise CoordinatorPolicyError("Missing repository head")
    if any(type(value) is not str or len(value) != 64 or
           any(c not in "0123456789abcdef" for c in value)
           for value in heads.values()):
        raise CoordinatorPolicyError("Invalid pinned repository head")
    keys = policy["gate_keys"]
    if type(keys) is not dict or not keys or len(keys) > 20:
        raise CoordinatorPolicyError("Invalid gate key map")
    for gate, gate_keys in keys.items():
        if type(gate) is not str or not 0 < len(gate) <= 256:
            raise CoordinatorPolicyError("Invalid gate ID")
        if type(gate_keys) is not dict or not gate_keys or len(gate_keys) > 10:
            raise CoordinatorPolicyError("Missing gate keys")
        for key_id, encoded in gate_keys.items():
            if type(key_id) is not str or not 0 < len(key_id) <= 256:
                raise CoordinatorPolicyError("Invalid key ID")
            if type(encoded) is not str:
                raise CoordinatorPolicyError("Invalid public key encoding")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise CoordinatorPolicyError("Invalid public key base64") from exc
            if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != encoded:
                raise CoordinatorPolicyError("Invalid Ed25519 public key")
    return policy


def decode_trusted_gate_keys(policy: dict[str, Any]) -> dict[str, dict[str, bytes]]:
    """Decode already-validated policy; callers must validate first."""
    return {
        gate: {key_id: base64.b64decode(value, validate=True)
               for key_id, value in gate_keys.items()}
        for gate, gate_keys in policy["gate_keys"].items()
    }


def load_coordinator_policy(path: str | Path) -> dict[str, Any]:
    """Load an OS-protected independent policy file; reject weak file modes.

    Path and parent directory must be coordinator-owned and not writable by
    other principals. POSIX permission checks are a partial defense; Windows
    ACL validation requires a separate platform-specific coordinator.
    """
    import os
    import stat
    candidate = Path(path)
    if not candidate.is_absolute():
        raise CoordinatorPolicyError("Policy path must be absolute")
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise CoordinatorPolicyError("Symlinked policy path")
    if not candidate.is_file():
        raise CoordinatorPolicyError("Policy must be a regular file")
    if os.name != "posix":
        raise CoordinatorPolicyError("Windows policy ACL verification not implemented")
    for part in (candidate, *candidate.parents):
        mode = part.stat().st_mode
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise CoordinatorPolicyError("Policy path is writable by other principals")
    if candidate.stat().st_size > 32768:
        raise CoordinatorPolicyError("Policy too large")
    return parse_coordinator_policy(candidate.read_bytes())
