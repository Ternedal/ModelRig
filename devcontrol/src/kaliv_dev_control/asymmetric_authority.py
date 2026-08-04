"""Verification-only asymmetric authority primitives.

This module intentionally contains no private-key type, signer, key loader,
credential adapter, transport or remote-write capability. Runtime authority may
receive pinned public verification identities and revocation state only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ASYMMETRIC_AUTHORITY_KEY_SCHEMA = "kaliv-asymmetric-authority-key/v1"
ASYMMETRIC_AUTHORITY_SIGNATURE_SCHEMA = "kaliv-asymmetric-authority-signature/v1"
ASYMMETRIC_AUTHORITY_ALGORITHM = "ed25519"
_SIGNATURE_DOMAIN = b"kaliv-asymmetric-authority-signature/v1\0"
_CUSTODY_POLICY_DOMAIN = b"kaliv-asymmetric-authority-key-custody-policy/v1\0"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX128 = re.compile(r"^[0-9a-f]{128}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_MAX_PAYLOAD_BYTES = 128 * 1024 * 1024

ASYMMETRIC_AUTHORITY_KEY_CUSTODY_POLICY = (
    "Private signing keys must never be stored in the repository, worker, Development Control Plane runtime, staged runtime closure or generated evidence.",
    "Signing must be performed by a separately authenticated offline, hardware-backed or equivalently isolated authority boundary.",
    "Runtime processes may receive only pinned Ed25519 public keys, immutable issuer identities, validity windows, keyring epochs and revocation state.",
    "Every signature must bind the exact key ID, issuer actor, issuer system, keyring epoch, custody-policy hash and payload bytes.",
    "Key rotation must increase the accepted keyring epoch; rollback to an older epoch fails closed.",
    "Revoked keys fail closed at verification time even when the signature predates revocation.",
)


class AsymmetricAuthorityError(ValueError):
    """Asymmetric authority evidence is malformed, untrusted or revoked."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AsymmetricAuthorityError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise AsymmetricAuthorityError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR_ID.fullmatch(value) is None:
        raise AsymmetricAuthorityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise AsymmetricAuthorityError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise AsymmetricAuthorityError(f"{name} is invalid") from exc


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AsymmetricAuthorityError(f"{name} is invalid")
    return value


def asymmetric_authority_key_custody_policy_sha256() -> str:
    payload = json.dumps(
        list(ASYMMETRIC_AUTHORITY_KEY_CUSTODY_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_CUSTODY_POLICY_DOMAIN + payload).hexdigest()


def authority_signing_message(
    *,
    key_id: str,
    issuer_actor_id: str,
    issuer_system_id: str,
    keyring_epoch: int,
    custody_policy_sha256: str,
    payload: bytes,
) -> bytes:
    """Build the exact domain-separated message an external signer must sign."""

    canonical_key_id = _identifier(key_id, name="authority key ID")
    actor = _actor(issuer_actor_id, name="authority issuer actor")
    system = _identifier(issuer_system_id, name="authority issuer system")
    if (
        not isinstance(keyring_epoch, int)
        or isinstance(keyring_epoch, bool)
        or keyring_epoch < 1
    ):
        raise AsymmetricAuthorityError("keyring epoch is invalid")
    policy_hash = _hex(
        custody_policy_sha256,
        name="authority key custody policy hash",
        pattern=_HEX64,
    )
    if policy_hash != asymmetric_authority_key_custody_policy_sha256():
        raise AsymmetricAuthorityError("authority key custody policy is unsupported")
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_PAYLOAD_BYTES:
        raise AsymmetricAuthorityError(
            "authority payload is invalid or exceeds its byte bound"
        )
    return (
        _SIGNATURE_DOMAIN
        + canonical_key_id.encode("utf-8")
        + b"\0"
        + actor.encode("utf-8")
        + b"\0"
        + system.encode("utf-8")
        + b"\0"
        + keyring_epoch.to_bytes(8, "big")
        + b"\0"
        + policy_hash.encode("ascii")
        + b"\0"
        + payload
    )


@dataclass(frozen=True, slots=True)
class TrustedEd25519AuthorityKey:
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    public_key_hex: str
    valid_from_utc: str
    valid_until_utc: str
    keyring_epoch: int
    custody_policy_sha256: str
    revoked_at_utc: str | None = None
    schema: str = ASYMMETRIC_AUTHORITY_KEY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ASYMMETRIC_AUTHORITY_KEY_SCHEMA:
            raise AsymmetricAuthorityError(
                "unsupported asymmetric authority key schema"
            )
        _identifier(self.key_id, name="authority key ID")
        _actor(self.issuer_actor_id, name="authority issuer actor")
        _identifier(self.issuer_system_id, name="authority issuer system")
        _hex(self.public_key_hex, name="Ed25519 public key", pattern=_HEX64)
        if (
            not isinstance(self.keyring_epoch, int)
            or isinstance(self.keyring_epoch, bool)
            or self.keyring_epoch < 1
        ):
            raise AsymmetricAuthorityError("keyring epoch is invalid")
        policy_hash = _hex(
            self.custody_policy_sha256,
            name="authority key custody policy hash",
            pattern=_HEX64,
        )
        if policy_hash != asymmetric_authority_key_custody_policy_sha256():
            raise AsymmetricAuthorityError(
                "authority key custody policy is unsupported"
            )
        valid_from = _utc(self.valid_from_utc, name="key validity start")
        valid_until = _utc(self.valid_until_utc, name="key validity end")
        if valid_until <= valid_from:
            raise AsymmetricAuthorityError(
                "authority key validity window is invalid"
            )
        if self.revoked_at_utc is not None:
            revoked = _utc(self.revoked_at_utc, name="key revocation time")
            if revoked < valid_from or revoked >= valid_until:
                raise AsymmetricAuthorityError(
                    "authority key revocation time is invalid"
                )
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        except ValueError as exc:
            raise AsymmetricAuthorityError("Ed25519 public key is invalid") from exc

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedEd25519AuthorityKey":
        data = _strict(
            value,
            name="trusted asymmetric authority key",
            fields={
                "schema",
                "key_id",
                "issuer_actor_id",
                "issuer_system_id",
                "public_key_hex",
                "valid_from_utc",
                "valid_until_utc",
                "keyring_epoch",
                "custody_policy_sha256",
                "revoked_at_utc",
            },
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "public_key_hex": self.public_key_hex,
            "valid_from_utc": self.valid_from_utc,
            "valid_until_utc": self.valid_until_utc,
            "keyring_epoch": self.keyring_epoch,
            "custody_policy_sha256": self.custody_policy_sha256,
            "revoked_at_utc": self.revoked_at_utc,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DetachedEd25519AuthoritySignature:
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    keyring_epoch: int
    custody_policy_sha256: str
    payload_sha256: str
    signature_hex: str
    signed_at_utc: str
    algorithm: str = ASYMMETRIC_AUTHORITY_ALGORITHM
    schema: str = ASYMMETRIC_AUTHORITY_SIGNATURE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ASYMMETRIC_AUTHORITY_SIGNATURE_SCHEMA:
            raise AsymmetricAuthorityError(
                "unsupported asymmetric authority signature schema"
            )
        if self.algorithm != ASYMMETRIC_AUTHORITY_ALGORITHM:
            raise AsymmetricAuthorityError(
                "asymmetric authority algorithm is unsupported"
            )
        _identifier(self.key_id, name="authority key ID")
        _actor(self.issuer_actor_id, name="authority issuer actor")
        _identifier(self.issuer_system_id, name="authority issuer system")
        if (
            not isinstance(self.keyring_epoch, int)
            or isinstance(self.keyring_epoch, bool)
            or self.keyring_epoch < 1
        ):
            raise AsymmetricAuthorityError("keyring epoch is invalid")
        policy_hash = _hex(
            self.custody_policy_sha256,
            name="authority key custody policy hash",
            pattern=_HEX64,
        )
        if policy_hash != asymmetric_authority_key_custody_policy_sha256():
            raise AsymmetricAuthorityError(
                "authority key custody policy is unsupported"
            )
        _hex(self.payload_sha256, name="authority payload hash", pattern=_HEX64)
        _hex(self.signature_hex, name="Ed25519 signature", pattern=_HEX128)
        _utc(self.signed_at_utc, name="authority signature time")

    @classmethod
    def from_mapping(cls, value: Any) -> "DetachedEd25519AuthoritySignature":
        data = _strict(
            value,
            name="detached asymmetric authority signature",
            fields={
                "schema",
                "algorithm",
                "key_id",
                "issuer_actor_id",
                "issuer_system_id",
                "keyring_epoch",
                "custody_policy_sha256",
                "payload_sha256",
                "signature_hex",
                "signed_at_utc",
            },
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "keyring_epoch": self.keyring_epoch,
            "custody_policy_sha256": self.custody_policy_sha256,
            "payload_sha256": self.payload_sha256,
            "signature_hex": self.signature_hex,
            "signed_at_utc": self.signed_at_utc,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class Ed25519AuthorityVerifier:
    """Verify detached evidence using only pinned public keys and revocation state."""

    def __init__(
        self,
        trusted_keys: Mapping[str, TrustedEd25519AuthorityKey],
        *,
        minimum_keyring_epoch: int,
    ) -> None:
        if not isinstance(trusted_keys, Mapping) or not trusted_keys:
            raise AsymmetricAuthorityError(
                "asymmetric verifier requires a non-empty keyring"
            )
        if (
            not isinstance(minimum_keyring_epoch, int)
            or isinstance(minimum_keyring_epoch, bool)
            or minimum_keyring_epoch < 1
        ):
            raise AsymmetricAuthorityError("minimum keyring epoch is invalid")
        keys: dict[str, TrustedEd25519AuthorityKey] = {}
        for key_id, trusted in trusted_keys.items():
            canonical_id = _identifier(key_id, name="trusted authority key ID")
            if (
                not isinstance(trusted, TrustedEd25519AuthorityKey)
                or trusted.key_id != canonical_id
            ):
                raise AsymmetricAuthorityError(
                    "trusted asymmetric keyring entry is invalid"
                )
            keys[canonical_id] = trusted
        self._trusted_keys = keys
        self._minimum_keyring_epoch = minimum_keyring_epoch

    def verify(
        self,
        *,
        payload: bytes,
        signature: DetachedEd25519AuthoritySignature,
        at_utc: str,
    ) -> str:
        if not isinstance(signature, DetachedEd25519AuthoritySignature):
            raise AsymmetricAuthorityError(
                "verification requires detached Ed25519 evidence"
            )
        observed_hash = hashlib.sha256(payload).hexdigest()
        if observed_hash != signature.payload_sha256:
            raise AsymmetricAuthorityError("authority payload hash mismatch")
        trusted = self._trusted_keys.get(signature.key_id)
        if trusted is None:
            raise AsymmetricAuthorityError("authority signing key is not trusted")
        if (
            trusted.issuer_actor_id != signature.issuer_actor_id
            or trusted.issuer_system_id != signature.issuer_system_id
        ):
            raise AsymmetricAuthorityError(
                "authority key is bound to another issuer identity"
            )
        if signature.keyring_epoch != trusted.keyring_epoch:
            raise AsymmetricAuthorityError("authority keyring epoch mismatch")
        if signature.keyring_epoch < self._minimum_keyring_epoch:
            raise AsymmetricAuthorityError("authority keyring epoch is stale")
        if signature.custody_policy_sha256 != trusted.custody_policy_sha256:
            raise AsymmetricAuthorityError(
                "authority key custody policy mismatch"
            )
        signed_at = _utc(signature.signed_at_utc, name="authority signature time")
        verified_at = _utc(at_utc, name="authority verification time")
        valid_from = _utc(trusted.valid_from_utc, name="key validity start")
        valid_until = _utc(trusted.valid_until_utc, name="key validity end")
        if signed_at > verified_at:
            raise AsymmetricAuthorityError("authority signature is from the future")
        if signed_at < valid_from or signed_at >= valid_until:
            raise AsymmetricAuthorityError(
                "authority signature is outside key validity"
            )
        if trusted.revoked_at_utc is not None:
            revoked = _utc(trusted.revoked_at_utc, name="key revocation time")
            if signed_at >= revoked or verified_at >= revoked:
                raise AsymmetricAuthorityError(
                    "authority signing key is revoked"
                )
        message = authority_signing_message(
            key_id=signature.key_id,
            issuer_actor_id=signature.issuer_actor_id,
            issuer_system_id=signature.issuer_system_id,
            keyring_epoch=signature.keyring_epoch,
            custody_policy_sha256=signature.custody_policy_sha256,
            payload=payload,
        )
        try:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(trusted.public_key_hex)
            ).verify(bytes.fromhex(signature.signature_hex), message)
        except InvalidSignature as exc:
            raise AsymmetricAuthorityError(
                "Ed25519 authority signature is invalid"
            ) from exc
        return observed_hash
