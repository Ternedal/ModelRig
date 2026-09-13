"""Host-pinned verification boundary for ADR-DC-015 human pilot decisions.

Production receives public verification material only. Signing remains an
external human action; this boundary starts no pilot and exposes no product
entrypoint or remote mutation capability.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)

HUMAN_PILOT_DECISION_KEYRING_SCHEMA = "kaliv-rsi-human-pilot-decision-keyring/v1"
HUMAN_PILOT_DECISION_AUTHORITY_DOMAIN = "rsi-dc-l16-human-pilot-decision"
_KEYRING_FIELDS = {"schema", "authority_domain", "minimum_keyring_epoch", "trusted_keys"}


class HumanPilotDecisionProductionBoundaryError(ValueError):
    """Production human-pilot decision trust state is unavailable or unsafe."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring is not canonical JSON"
        ) from exc


def _canonical_human_pilot_decision_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-human-pilot-decision-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-human-pilot-decision-keyring-v1.json"
        )
    raise HumanPilotDecisionProductionBoundaryError(
        "human pilot decision authority keyring is unsupported on this platform"
    )


def _load_human_pilot_decision_verifier_at(
    path: Path,
    *,
    issuer_system_id: str,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    try:
        payload = _read_keyring_bytes(Path(path), require_host_control=require_host_control)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring fields mismatch"
        )
    if value.get("schema") != HUMAN_PILOT_DECISION_KEYRING_SCHEMA:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != HUMAN_PILOT_DECISION_AUTHORITY_DOMAIN:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring must contain trusted public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise HumanPilotDecisionProductionBoundaryError(
                    "human pilot decision authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise HumanPilotDecisionProductionBoundaryError(
                    "human pilot decision authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except HumanPilotDecisionProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": HUMAN_PILOT_DECISION_KEYRING_SCHEMA,
        "authority_domain": HUMAN_PILOT_DECISION_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision authority keyring is not canonical"
        )
    return verifier


def _canonical_human_pilot_decision_verifier(
    *,
    issuer_system_id: str,
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision verification requires an elevated host operator"
        ) from exc
    return _load_human_pilot_decision_verifier_at(
        _canonical_human_pilot_decision_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def install_human_pilot_decision_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise HumanPilotDecisionProductionBoundaryError(
            "human pilot decision implementation is unavailable"
        )
    if getattr(implementation, "_production_human_pilot_decision_boundary_installed", False):
        return
    private_verify = implementation._verify_human_pilot_decision

    def verify_human_pilot_decision(
        *,
        completion_proof: Any,
        decision: Any,
        signature: Any,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.HumanPilotDecisionError(
                "caller-selected human pilot decision verifier is not production authority"
            )
        try:
            host_verifier = _canonical_human_pilot_decision_verifier(
                issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
            )
        except HumanPilotDecisionProductionBoundaryError as exc:
            raise implementation.HumanPilotDecisionError(
                "host-controlled human pilot decision authority state is unavailable"
            ) from exc
        return private_verify(
            completion_proof=completion_proof,
            decision=decision,
            signature=signature,
            verifier=host_verifier,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.verify_human_pilot_decision = verify_human_pilot_decision
    implementation._production_human_pilot_decision_boundary_installed = True


__all__: list[str] = []
