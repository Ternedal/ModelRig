"""Host-pinned verification boundary for ADR-DC-023 runtime-preflight attestation."""
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

PILOT_RUNTIME_PREFLIGHT_ATTESTATION_KEYRING_SCHEMA = (
    "kaliv-rsi-runtime-preflight-attestation-keyring/v1"
)
PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY_DOMAIN = (
    "rsi-dc-l16-runtime-preflight-attestation"
)
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PilotRuntimePreflightAttestationProductionBoundaryError(ValueError):
    """Production preflight-attestation trust state is unavailable or unsafe."""


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
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring is not canonical JSON"
        ) from exc


def _canonical_pilot_runtime_preflight_attestation_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-runtime-preflight-attestation-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-runtime-preflight-attestation-keyring-v1.json"
        )
    raise PilotRuntimePreflightAttestationProductionBoundaryError(
        "runtime preflight attestation keyring is unsupported on this platform"
    )


def _load_pilot_runtime_preflight_attestation_verifier_at(
    path: Path,
    *,
    issuer_system_id: str,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    try:
        payload = _read_keyring_bytes(
            Path(path), require_host_control=require_host_control
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring fields mismatch"
        )
    if value.get("schema") != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_KEYRING_SCHEMA:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring schema is unsupported"
        )
    if (
        value.get("authority_domain")
        != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY_DOMAIN
    ):
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring must contain trusted public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise PilotRuntimePreflightAttestationProductionBoundaryError(
                    "runtime preflight attestation key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PilotRuntimePreflightAttestationProductionBoundaryError(
                    "runtime preflight attestation keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PilotRuntimePreflightAttestationProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": PILOT_RUNTIME_PREFLIGHT_ATTESTATION_KEYRING_SCHEMA,
        "authority_domain": PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation keyring is not canonical"
        )
    return verifier


def _canonical_pilot_runtime_preflight_attestation_verifier(
    *, issuer_system_id: str
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation verification requires an elevated host operator"
        ) from exc
    return _load_pilot_runtime_preflight_attestation_verifier_at(
        _canonical_pilot_runtime_preflight_attestation_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def install_pilot_runtime_preflight_attestation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotRuntimePreflightAttestationProductionBoundaryError(
            "runtime preflight attestation implementation is unavailable"
        )
    if getattr(
        implementation,
        "_production_pilot_runtime_preflight_attestation_boundary_installed",
        False,
    ):
        return
    private_verify = implementation._verify_pilot_runtime_preflight_attestation

    def verify_pilot_runtime_preflight_attestation(
        *,
        attestation: Any,
        signature: Any,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.PilotRuntimePreflightAttestationError(
                "caller-selected runtime preflight attestation verifier is not production authority"
            )
        try:
            host_verifier = _canonical_pilot_runtime_preflight_attestation_verifier(
                issuer_system_id=(
                    implementation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
                )
            )
        except PilotRuntimePreflightAttestationProductionBoundaryError as exc:
            raise implementation.PilotRuntimePreflightAttestationError(
                "host-controlled runtime preflight attestation authority state is unavailable"
            ) from exc
        return private_verify(
            attestation=attestation,
            signature=signature,
            verifier=host_verifier,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.verify_pilot_runtime_preflight_attestation = (
        verify_pilot_runtime_preflight_attestation
    )
    implementation._production_pilot_runtime_preflight_attestation_boundary_installed = (
        True
    )


__all__: list[str] = []
