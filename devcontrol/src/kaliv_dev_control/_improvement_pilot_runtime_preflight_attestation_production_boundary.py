"""Host-pinned verification boundary for ADR-DC-022 runtime preflight evidence."""
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

PILOT_RUNTIME_PREFLIGHT_KEYRING_SCHEMA = (
    "kaliv-rsi-pilot-runtime-preflight-keyring/v1"
)
PILOT_RUNTIME_PREFLIGHT_AUTHORITY_DOMAIN = "rsi-dc-l16-pilot-runtime-preflight"
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PilotRuntimePreflightProductionBoundaryError(ValueError):
    """Production runtime-preflight trust state is unavailable or unsafe."""


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
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring is not canonical JSON"
        ) from exc


def _canonical_pilot_runtime_preflight_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-runtime-preflight-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-pilot-runtime-preflight-keyring-v1.json"
        )
    raise PilotRuntimePreflightProductionBoundaryError(
        "runtime preflight authority keyring is unsupported on this platform"
    )


def _load_pilot_runtime_preflight_verifier_at(
    path: Path,
    *,
    issuer_system_id: str,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    try:
        payload = _read_keyring_bytes(Path(path), require_host_control=require_host_control)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring fields mismatch"
        )
    if value.get("schema") != PILOT_RUNTIME_PREFLIGHT_KEYRING_SCHEMA:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != PILOT_RUNTIME_PREFLIGHT_AUTHORITY_DOMAIN:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring must contain trusted public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise PilotRuntimePreflightProductionBoundaryError(
                    "runtime preflight authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PilotRuntimePreflightProductionBoundaryError(
                    "runtime preflight authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PilotRuntimePreflightProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": PILOT_RUNTIME_PREFLIGHT_KEYRING_SCHEMA,
        "authority_domain": PILOT_RUNTIME_PREFLIGHT_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight authority keyring is not canonical"
        )
    return verifier


def _canonical_pilot_runtime_preflight_verifier(
    *,
    issuer_system_id: str,
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight verification requires an elevated host operator"
        ) from exc
    return _load_pilot_runtime_preflight_verifier_at(
        _canonical_pilot_runtime_preflight_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def install_pilot_runtime_preflight_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PilotRuntimePreflightProductionBoundaryError(
            "runtime preflight implementation is unavailable"
        )
    if getattr(implementation, "_production_pilot_runtime_preflight_boundary_installed", False):
        return
    private_verify = implementation._verify_pilot_runtime_preflight

    def verify_pilot_runtime_preflight(
        *,
        selection_proof: Any,
        requirements: Any,
        observation: Any,
        signature: Any,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.PilotRuntimePreflightError(
                "caller-selected runtime preflight verifier is not production authority"
            )
        try:
            host_verifier = _canonical_pilot_runtime_preflight_verifier(
                issuer_system_id=implementation.PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID,
            )
        except PilotRuntimePreflightProductionBoundaryError as exc:
            raise implementation.PilotRuntimePreflightError(
                "host-controlled runtime preflight authority state is unavailable"
            ) from exc
        return private_verify(
            selection_proof=selection_proof,
            requirements=requirements,
            observation=observation,
            signature=signature,
            verifier=host_verifier,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.verify_pilot_runtime_preflight = verify_pilot_runtime_preflight
    implementation._production_pilot_runtime_preflight_boundary_installed = True


__all__: list[str] = []
