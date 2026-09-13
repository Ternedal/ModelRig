"""Host-controlled Ed25519 trust root for RSI physical request verification.

This module is verification-only. It never loads a private key, signs data,
contacts a network service, or grants physical execution authority. Production
verification reads one fixed host-admin-controlled public-keyring file and fails
closed when that trust root is missing, malformed, mutable by ordinary POSIX
users, or belongs to another authority domain.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_request import PHYSICAL_REQUEST_ISSUER_SYSTEM_ID
from .trusted_git_runtime_model import _has_linkish_component

PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA = (
    "kaliv-rsi-physical-request-authority-keyring/v1"
)
PHYSICAL_REQUEST_AUTHORITY_DOMAIN = "rsi-dc-l15-physical-request"
_MAX_KEYRING_BYTES = 256 * 1024
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PhysicalRequestAuthorityKeyringError(ValueError):
    """The host-controlled physical-request verification trust root is invalid."""


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
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not canonical JSON"
        ) from exc


def _canonical_physical_request_authority_keyring_path() -> Path:
    """Return the fixed host-admin path; callers cannot select this location."""

    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-physical-request-authority-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-request-authority-keyring-v1.json"
        )
    raise PhysicalRequestAuthorityKeyringError(
        "physical request authority keyring is unsupported on this platform"
    )


def _require_posix_host_control(path: Path, observed: os.stat_result) -> None:
    """Require a root-owned keyring under a root-owned non-writable directory chain."""

    if os.name != "posix":
        return
    if observed.st_uid != 0 or stat.S_IMODE(observed.st_mode) & 0o022:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not root-controlled"
        )
    cursor = path.parent
    while True:
        try:
            directory = cursor.stat()
        except OSError as exc:
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring parent is unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 0
            or stat.S_IMODE(directory.st_mode) & 0o022
        ):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring directory chain is not root-controlled"
            )
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


def _read_keyring_bytes(
    path: Path,
    *,
    require_host_control: bool,
) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring path is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is missing or unreadable"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size < 1
            or observed.st_size > _MAX_KEYRING_BYTES
        ):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring file is unsafe"
            )
        if require_host_control:
            _require_posix_host_control(candidate, observed)
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority keyring read was incomplete"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring changed while reading"
            )
        return b"".join(chunks)
    except OSError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)


def _load_physical_request_authority_verifier_at(
    path: Path,
    *,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    """Load one exact public verification keyring; never caller-selected in production."""

    payload = _read_keyring_bytes(
        path,
        require_host_control=require_host_control,
    )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring fields mismatch"
        )
    if value.get("schema") != PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != PHYSICAL_REQUEST_AUTHORITY_DOMAIN:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring must contain trusted public keys"
        )

    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != PHYSICAL_REQUEST_ISSUER_SYSTEM_ID:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except AsymmetricAuthorityError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring contains invalid public-key evidence"
        ) from exc

    canonical_mapping = {
        "schema": PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA,
        "authority_domain": PHYSICAL_REQUEST_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not canonical"
        )
    return verifier


def _canonical_physical_request_authority_verifier() -> Ed25519AuthorityVerifier:
    """Resolve the production trust root from the fixed host-admin keyring path."""

    return _load_physical_request_authority_verifier_at(
        _canonical_physical_request_authority_keyring_path(),
        require_host_control=True,
    )


__all__: list[str] = []
