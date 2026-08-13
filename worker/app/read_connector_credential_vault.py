"""Dormant encrypted credential vault for T-037 Google/Notion read connectors.

The vault is host-owned infrastructure behind ``ReadConnectorCredentialProvider``.
It persists only encrypted credential material and encrypted identity/readiness
metadata. The file name and outer envelope contain hashes/provider identifiers,
never account/workspace references or bearer text.

This slice deliberately stops before OAuth refresh/network exchange and before
normal worker registration. A host must inject an explicit absolute vault root
and construct the provider itself. ``PRODUCTION_ACTIVATION`` remains false.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from .read_connector_credential_binding import (
    CredentialKind,
    ReadConnectorCredentialEvidence,
)
from .read_connector_package_contract import Connector, normalize_connector

VAULT_SCHEMA = "kaliv-read-connector-credential-vault/v1"
EVIDENCE_PAYLOAD_SCHEMA = "kaliv-read-connector-credential-vault-evidence/v1"
PRODUCTION_ACTIVATION = False
WINDOWS_PROVIDER = "windows-dpapi-current-user"
KEY_SCOPE_CURRENT_USER = "current-user"

_EXPECTED_KIND: dict[str, CredentialKind] = {
    "google_calendar": "google_oauth_bearer",
    "google_drive": "google_oauth_bearer",
    "gmail": "google_oauth_bearer",
    "notion": "notion_integration_bearer",
}
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_BEARER_BYTES = 4_096
_MAX_EVIDENCE_BYTES = 8_192
_MAX_CIPHERTEXT_BYTES = 32_768
_MAX_ENVELOPE_BYTES = 96_000
_ENVELOPE_KEYS = frozenset(
    {
        "schema",
        "provider",
        "key_scope",
        "scope_sha256",
        "evidence_ciphertext_sha256",
        "evidence_ciphertext_b64",
        "bearer_ciphertext_sha256",
        "bearer_ciphertext_b64",
    }
)
_EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "connector",
        "account_ref",
        "workspace_ref",
        "credential_kind",
        "stored_at",
        "expires_at",
        "revoked_at",
    }
)


class ReadConnectorCredentialVaultError(RuntimeError):
    """Encrypted connector credential storage failed without exposing secret data."""


class CredentialProtector(Protocol):
    provider_id: str
    key_scope: str

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        ...

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        ...


def _uint(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadConnectorCredentialVaultError(f"{name} must be a non-negative integer")
    return value


def _ref(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorCredentialVaultError(f"{name} must be a string")
    normalized = value.strip()
    if not _REF.fullmatch(normalized):
        raise ReadConnectorCredentialVaultError(
            f"{name} must be an exact stable provider identifier"
        )
    return normalized


def _canonical_json(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReadConnectorCredentialVaultError(
            "credential vault content is not canonical JSON"
        ) from exc


def _strict_object(raw: bytes, *, max_bytes: int, label: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise ReadConnectorCredentialVaultError(f"{label} size is invalid")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ReadConnectorCredentialVaultError(
                    f"{label} contains duplicate JSON keys"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ReadConnectorCredentialVaultError(
                    f"{label} contains a non-finite number"
                )
            ),
        )
    except ReadConnectorCredentialVaultError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadConnectorCredentialVaultError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ReadConnectorCredentialVaultError(f"{label} must be a JSON object")
    return value


def _ciphertext_from_envelope(
    value: dict[str, Any],
    *,
    b64_key: str,
    digest_key: str,
) -> bytes:
    encoded = value.get(b64_key)
    digest = value.get(digest_key)
    if not isinstance(encoded, str) or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ReadConnectorCredentialVaultError("credential vault ciphertext metadata is invalid")
    try:
        ciphertext = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ReadConnectorCredentialVaultError(
            "credential vault ciphertext encoding is invalid"
        ) from exc
    if not ciphertext or len(ciphertext) > _MAX_CIPHERTEXT_BYTES:
        raise ReadConnectorCredentialVaultError("credential vault ciphertext size is invalid")
    if hashlib.sha256(ciphertext).hexdigest() != digest:
        raise ReadConnectorCredentialVaultError("credential vault ciphertext digest mismatch")
    return ciphertext


def _validated_bearer(value: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorCredentialVaultError("connector bearer token must be a string")
    if not 20 <= len(value) <= _MAX_BEARER_BYTES:
        raise ReadConnectorCredentialVaultError("connector bearer token length is invalid")
    if value != value.strip() or not value.isascii():
        raise ReadConnectorCredentialVaultError("connector bearer token format is invalid")
    if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise ReadConnectorCredentialVaultError("connector bearer token format is invalid")
    return value


@dataclass(frozen=True)
class CredentialVaultScope:
    """Exact connector identity bound into file naming and protector entropy."""

    connector: Connector
    account_ref: str
    workspace_ref: str | None = None
    credential_kind: CredentialKind | None = None

    def __post_init__(self) -> None:
        connector = normalize_connector(self.connector)
        account_ref = _ref(self.account_ref, "vault account_ref")
        workspace_ref = (
            _ref(self.workspace_ref, "vault workspace_ref")
            if self.workspace_ref is not None
            else None
        )
        expected_kind = _EXPECTED_KIND[connector]
        credential_kind = self.credential_kind or expected_kind
        if credential_kind != expected_kind:
            raise ReadConnectorCredentialVaultError(
                "vault credential kind does not match connector"
            )
        if connector == "notion":
            if workspace_ref is None:
                raise ReadConnectorCredentialVaultError(
                    "Notion credential vault requires workspace_ref"
                )
        elif workspace_ref is not None:
            raise ReadConnectorCredentialVaultError(
                "Google credential vault cannot carry workspace_ref"
            )
        object.__setattr__(self, "connector", connector)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "workspace_ref", workspace_ref)
        object.__setattr__(self, "credential_kind", credential_kind)

    def canonical_bytes(self) -> bytes:
        return _canonical_json(
            {
                "namespace": "read-connector-credential-vault",
                "connector": self.connector,
                "account_ref": self.account_ref,
                "workspace_ref": self.workspace_ref,
                "credential_kind": self.credential_kind,
            }
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def entropy(self, purpose: str, *, evidence_ciphertext_sha256: str | None = None) -> bytes:
        if purpose not in {"evidence", "bearer"}:
            raise ReadConnectorCredentialVaultError("credential protector purpose is invalid")
        if purpose == "bearer":
            if (
                not isinstance(evidence_ciphertext_sha256, str)
                or not _SHA256.fullmatch(evidence_ciphertext_sha256)
            ):
                raise ReadConnectorCredentialVaultError(
                    "bearer protection requires evidence ciphertext binding"
                )
        elif evidence_ciphertext_sha256 is not None:
            raise ReadConnectorCredentialVaultError(
                "evidence protection cannot carry bearer binding"
            )
        binding = _canonical_json(
            {
                "schema": VAULT_SCHEMA,
                "scope_sha256": self.sha256,
                "purpose": purpose,
                "evidence_ciphertext_sha256": evidence_ciphertext_sha256,
            }
        )
        return hashlib.sha256(binding).digest()


class WindowsDpapiCredentialProtector:
    """Windows DPAPI current-user protector with interactive UI forbidden."""

    provider_id = WINDOWS_PROVIDER
    key_scope = KEY_SCOPE_CURRENT_USER
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _DESCRIPTION = "Kaliv read connector credential"

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def __init__(self, *, os_name: str | None = None) -> None:
        self._os_name = os_name or os.name
        if self._os_name != "nt":
            raise ReadConnectorCredentialVaultError(
                "connector credential protection requires Windows DPAPI"
            )
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise ReadConnectorCredentialVaultError(
                "Windows DPAPI is unavailable for connector credentials"
            ) from exc

        blob_ptr = ctypes.POINTER(self._DATA_BLOB)
        self._crypt32.CryptProtectData.argtypes = [
            blob_ptr,
            ctypes.c_wchar_p,
            blob_ptr,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_ptr,
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            blob_ptr,
            ctypes.c_void_p,
            blob_ptr,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_ptr,
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @classmethod
    def _input_blob(
        cls, value: bytes
    ) -> tuple["WindowsDpapiCredentialProtector._DATA_BLOB", Any]:
        if not isinstance(value, bytes) or not value:
            raise ReadConnectorCredentialVaultError(
                "credential protection input must be non-empty bytes"
            )
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        blob = cls._DATA_BLOB(
            len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        return blob, buffer

    def _output_bytes(self, output: _DATA_BLOB) -> bytes:
        if output.cbData <= 0 or not output.pbData:
            raise ReadConnectorCredentialVaultError(
                "Windows DPAPI returned an empty connector credential value"
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        source, source_buffer = self._input_blob(plaintext)
        extra, entropy_buffer = self._input_blob(entropy)
        output = self._DATA_BLOB()
        try:
            ok = self._crypt32.CryptProtectData(
                ctypes.byref(source),
                self._DESCRIPTION,
                ctypes.byref(extra),
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not ok:
                raise ReadConnectorCredentialVaultError(
                    "Windows could not protect connector credential material"
                )
            return self._output_bytes(output)
        finally:
            ctypes.memset(source_buffer, 0, len(source_buffer))
            ctypes.memset(entropy_buffer, 0, len(entropy_buffer))

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        source, source_buffer = self._input_blob(ciphertext)
        extra, entropy_buffer = self._input_blob(entropy)
        output = self._DATA_BLOB()
        try:
            ok = self._crypt32.CryptUnprotectData(
                ctypes.byref(source),
                None,
                ctypes.byref(extra),
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not ok:
                raise ReadConnectorCredentialVaultError(
                    "Windows could not unlock connector credential material"
                )
            return self._output_bytes(output)
        finally:
            ctypes.memset(source_buffer, 0, len(source_buffer))
            ctypes.memset(entropy_buffer, 0, len(entropy_buffer))


class ReadConnectorCredentialVault:
    """Atomic encrypted file vault implementing the credential-provider protocol."""

    def __init__(
        self,
        *,
        root: Path | str,
        scope: CredentialVaultScope,
        protector: CredentialProtector,
    ) -> None:
        if not isinstance(scope, CredentialVaultScope):
            raise ReadConnectorCredentialVaultError(
                "credential vault requires CredentialVaultScope"
            )
        root_path = Path(root)
        if not root_path.is_absolute():
            raise ReadConnectorCredentialVaultError(
                "credential vault root must be an explicit absolute path"
            )
        provider_id = getattr(protector, "provider_id", None)
        key_scope = getattr(protector, "key_scope", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ReadConnectorCredentialVaultError("credential protector provider_id is missing")
        if not isinstance(key_scope, str) or not key_scope.strip():
            raise ReadConnectorCredentialVaultError("credential protector key_scope is missing")
        self._root = root_path
        self._scope = scope
        self._protector = protector
        self._lock = RLock()

    def store_bearer(
        self,
        bearer_token: str,
        *,
        now: int,
        expires_at: int | None = None,
    ) -> None:
        now = _uint(now, "credential stored_at")
        token = _validated_bearer(bearer_token)
        if expires_at is not None:
            expires_at = _uint(expires_at, "credential expires_at")
            if expires_at <= now:
                raise ReadConnectorCredentialVaultError(
                    "credential expires_at must be after stored_at"
                )
        if self._scope.connector != "notion" and expires_at is None:
            raise ReadConnectorCredentialVaultError(
                "Google OAuth credential storage requires expires_at"
            )

        evidence_payload = self._evidence_payload(
            stored_at=now,
            expires_at=expires_at,
            revoked_at=None,
        )
        evidence_clear = bytearray(_canonical_json(evidence_payload))
        bearer_clear = bytearray(token.encode("ascii"))
        try:
            evidence_ciphertext = self._protect(
                bytes(evidence_clear),
                entropy=self._scope.entropy("evidence"),
            )
            evidence_ciphertext_sha256 = hashlib.sha256(evidence_ciphertext).hexdigest()
            bearer_ciphertext = self._protect(
                bytes(bearer_clear),
                entropy=self._scope.entropy(
                    "bearer",
                    evidence_ciphertext_sha256=evidence_ciphertext_sha256,
                ),
            )
        finally:
            _wipe(evidence_clear)
            _wipe(bearer_clear)

        envelope = self._envelope(
            evidence_ciphertext=evidence_ciphertext,
            bearer_ciphertext=bearer_ciphertext,
        )
        self._atomic_write(envelope)

    def evidence(self, *, now: int) -> ReadConnectorCredentialEvidence:
        now = _uint(now, "credential check time")
        with self._lock:
            try:
                envelope = self._read_envelope()
            except OSError:
                return self._state_evidence("unavailable", now=now)
            except ReadConnectorCredentialVaultError:
                return self._state_evidence("invalid_credentials", now=now)
            if envelope is None:
                return self._state_evidence("missing_credentials", now=now)

            try:
                payload = self._decrypt_evidence(envelope)
            except ReadConnectorCredentialVaultError:
                return self._state_evidence("invalid_credentials", now=now)

            expires_at = payload["expires_at"]
            revoked_at = payload["revoked_at"]
            if revoked_at is not None and revoked_at <= now:
                return self._state_evidence(
                    "invalid_credentials", now=now, expires_at=expires_at
                )
            if expires_at is not None and expires_at <= now:
                return self._state_evidence(
                    "expired_credentials", now=now, expires_at=expires_at
                )
            return self._state_evidence("ready", now=now, expires_at=expires_at)

    def bearer_token(self) -> str:
        with self._lock:
            try:
                envelope = self._read_envelope()
                if envelope is None:
                    raise ReadConnectorCredentialVaultError(
                        "connector credential material is unavailable"
                    )
                payload = self._decrypt_evidence(envelope)
                if payload["revoked_at"] is not None:
                    raise ReadConnectorCredentialVaultError(
                        "connector credential material is unavailable"
                    )
                evidence_digest = envelope["evidence_ciphertext_sha256"]
                bearer_ciphertext = _ciphertext_from_envelope(
                    envelope,
                    b64_key="bearer_ciphertext_b64",
                    digest_key="bearer_ciphertext_sha256",
                )
                clear = self._unprotect(
                    bearer_ciphertext,
                    entropy=self._scope.entropy(
                        "bearer",
                        evidence_ciphertext_sha256=evidence_digest,
                    ),
                )
                clear_for_wipe = bytearray(clear)
                try:
                    try:
                        token = bytes(clear_for_wipe).decode("ascii", errors="strict")
                    except UnicodeDecodeError as exc:
                        raise ReadConnectorCredentialVaultError(
                            "connector credential material is unavailable"
                        ) from exc
                    return _validated_bearer(token)
                finally:
                    _wipe(clear_for_wipe)
            except ReadConnectorCredentialVaultError:
                raise
            except OSError:
                raise ReadConnectorCredentialVaultError(
                    "connector credential material is unavailable"
                ) from None
            except Exception:
                raise ReadConnectorCredentialVaultError(
                    "connector credential material is unavailable"
                ) from None

    def revoke(self, *, now: int) -> bool:
        now = _uint(now, "credential revoke time")
        with self._lock:
            try:
                envelope = self._read_envelope()
            except OSError:
                raise ReadConnectorCredentialVaultError(
                    "connector credential vault is unavailable"
                ) from None
            if envelope is None:
                return False
            payload = self._decrypt_evidence(envelope)
            if payload["revoked_at"] is not None:
                return False
            payload["revoked_at"] = now
            evidence_clear = bytearray(_canonical_json(payload))
            try:
                evidence_ciphertext = self._protect(
                    bytes(evidence_clear),
                    entropy=self._scope.entropy("evidence"),
                )
            finally:
                _wipe(evidence_clear)
            bearer_ciphertext = _ciphertext_from_envelope(
                envelope,
                b64_key="bearer_ciphertext_b64",
                digest_key="bearer_ciphertext_sha256",
            )
            # Once evidence is revoked bearer_token() fails before bearer
            # decryption, so the old ciphertext can remain sealed in place.
            self._atomic_write(
                self._envelope(
                    evidence_ciphertext=evidence_ciphertext,
                    bearer_ciphertext=bearer_ciphertext,
                )
            )
            return True

    def clear(self) -> bool:
        with self._lock:
            path = self._path()
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise ReadConnectorCredentialVaultError(
                    "connector credential vault could not remove record"
                ) from exc
            self._fsync_directory()
            return True

    def _state_evidence(
        self,
        state: str,
        *,
        now: int,
        expires_at: int | None = None,
    ) -> ReadConnectorCredentialEvidence:
        return ReadConnectorCredentialEvidence(
            connector=self._scope.connector,
            account_ref=self._scope.account_ref,
            workspace_ref=self._scope.workspace_ref,
            credential_kind=self._scope.credential_kind,
            state=state,
            checked_at=now,
            expires_at=expires_at,
        )

    def _evidence_payload(
        self,
        *,
        stored_at: int,
        expires_at: int | None,
        revoked_at: int | None,
    ) -> dict[str, Any]:
        return {
            "schema": EVIDENCE_PAYLOAD_SCHEMA,
            "connector": self._scope.connector,
            "account_ref": self._scope.account_ref,
            "workspace_ref": self._scope.workspace_ref,
            "credential_kind": self._scope.credential_kind,
            "stored_at": stored_at,
            "expires_at": expires_at,
            "revoked_at": revoked_at,
        }

    def _validate_evidence_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != _EVIDENCE_KEYS:
            raise ReadConnectorCredentialVaultError(
                "credential vault evidence keys mismatch"
            )
        if payload.get("schema") != EVIDENCE_PAYLOAD_SCHEMA:
            raise ReadConnectorCredentialVaultError(
                "credential vault evidence schema is unsupported"
            )
        if (
            payload.get("connector") != self._scope.connector
            or payload.get("account_ref") != self._scope.account_ref
            or payload.get("workspace_ref") != self._scope.workspace_ref
            or payload.get("credential_kind") != self._scope.credential_kind
        ):
            raise ReadConnectorCredentialVaultError(
                "credential vault evidence identity mismatch"
            )
        stored_at = _uint(payload.get("stored_at"), "credential stored_at")
        expires_at = payload.get("expires_at")
        revoked_at = payload.get("revoked_at")
        if expires_at is not None:
            expires_at = _uint(expires_at, "credential expires_at")
            if expires_at <= stored_at:
                raise ReadConnectorCredentialVaultError(
                    "credential vault expiry is not after stored_at"
                )
        if self._scope.connector != "notion" and expires_at is None:
            raise ReadConnectorCredentialVaultError(
                "Google OAuth credential evidence requires expires_at"
            )
        if revoked_at is not None:
            revoked_at = _uint(revoked_at, "credential revoked_at")
            if revoked_at < stored_at:
                raise ReadConnectorCredentialVaultError(
                    "credential vault revoke time predates stored_at"
                )
        payload["stored_at"] = stored_at
        payload["expires_at"] = expires_at
        payload["revoked_at"] = revoked_at
        return payload

    def _decrypt_evidence(self, envelope: dict[str, Any]) -> dict[str, Any]:
        ciphertext = _ciphertext_from_envelope(
            envelope,
            b64_key="evidence_ciphertext_b64",
            digest_key="evidence_ciphertext_sha256",
        )
        clear = self._unprotect(
            ciphertext,
            entropy=self._scope.entropy("evidence"),
        )
        clear_for_wipe = bytearray(clear)
        try:
            payload = _strict_object(
                bytes(clear_for_wipe),
                max_bytes=_MAX_EVIDENCE_BYTES,
                label="credential vault evidence",
            )
        finally:
            _wipe(clear_for_wipe)
        return self._validate_evidence_payload(payload)

    def _protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        try:
            ciphertext = self._protector.protect(plaintext, entropy=entropy)
        except ReadConnectorCredentialVaultError:
            raise
        except Exception:
            raise ReadConnectorCredentialVaultError(
                "credential protection provider failed"
            ) from None
        if (
            not isinstance(ciphertext, bytes)
            or not ciphertext
            or len(ciphertext) > _MAX_CIPHERTEXT_BYTES
        ):
            raise ReadConnectorCredentialVaultError(
                "credential protection provider returned invalid ciphertext"
            )
        return ciphertext

    def _unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        try:
            clear = self._protector.unprotect(ciphertext, entropy=entropy)
        except ReadConnectorCredentialVaultError:
            raise
        except Exception:
            raise ReadConnectorCredentialVaultError(
                "credential protection provider could not open value"
            ) from None
        if not isinstance(clear, bytes) or not clear:
            raise ReadConnectorCredentialVaultError(
                "credential protection provider returned invalid plaintext"
            )
        return clear

    def _envelope(
        self,
        *,
        evidence_ciphertext: bytes,
        bearer_ciphertext: bytes,
    ) -> dict[str, Any]:
        return {
            "schema": VAULT_SCHEMA,
            "provider": self._protector.provider_id,
            "key_scope": self._protector.key_scope,
            "scope_sha256": self._scope.sha256,
            "evidence_ciphertext_sha256": hashlib.sha256(
                evidence_ciphertext
            ).hexdigest(),
            "evidence_ciphertext_b64": base64.b64encode(
                evidence_ciphertext
            ).decode("ascii"),
            "bearer_ciphertext_sha256": hashlib.sha256(
                bearer_ciphertext
            ).hexdigest(),
            "bearer_ciphertext_b64": base64.b64encode(
                bearer_ciphertext
            ).decode("ascii"),
        }

    def _read_envelope(self) -> dict[str, Any] | None:
        path = self._path()
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        value = _strict_object(
            raw,
            max_bytes=_MAX_ENVELOPE_BYTES,
            label="credential vault envelope",
        )
        if set(value) != _ENVELOPE_KEYS:
            raise ReadConnectorCredentialVaultError(
                "credential vault envelope keys mismatch"
            )
        if value.get("schema") != VAULT_SCHEMA:
            raise ReadConnectorCredentialVaultError(
                "credential vault envelope schema is unsupported"
            )
        if (
            value.get("provider") != self._protector.provider_id
            or value.get("key_scope") != self._protector.key_scope
        ):
            raise ReadConnectorCredentialVaultError(
                "credential vault protector identity mismatch"
            )
        if value.get("scope_sha256") != self._scope.sha256:
            raise ReadConnectorCredentialVaultError(
                "credential vault scope digest mismatch"
            )
        _ciphertext_from_envelope(
            value,
            b64_key="evidence_ciphertext_b64",
            digest_key="evidence_ciphertext_sha256",
        )
        _ciphertext_from_envelope(
            value,
            b64_key="bearer_ciphertext_b64",
            digest_key="bearer_ciphertext_sha256",
        )
        return value

    def _path(self) -> Path:
        return self._root / f"{self._scope.sha256}.credential.json"

    def _atomic_write(self, envelope: dict[str, Any]) -> None:
        payload = _canonical_json(envelope) + b"\n"
        if len(payload) > _MAX_ENVELOPE_BYTES:
            raise ReadConnectorCredentialVaultError(
                "credential vault envelope exceeds size limit"
            )
        with self._lock:
            try:
                self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
                if os.name != "nt":
                    os.chmod(self._root, 0o700)
                destination = self._path()
                temporary_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        prefix=f".{destination.name}.",
                        suffix=".tmp",
                        dir=self._root,
                        delete=False,
                    ) as handle:
                        temporary_path = Path(handle.name)
                        if os.name != "nt":
                            os.chmod(temporary_path, 0o600)
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_path, destination)
                    if os.name != "nt":
                        os.chmod(destination, 0o600)
                    self._fsync_directory()
                except Exception:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                    raise
            except ReadConnectorCredentialVaultError:
                raise
            except OSError:
                raise ReadConnectorCredentialVaultError(
                    "connector credential vault could not persist record"
                ) from None

    def _fsync_directory(self) -> None:
        if os.name == "nt" or not self._root.exists():
            return
        try:
            descriptor = os.open(self._root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
