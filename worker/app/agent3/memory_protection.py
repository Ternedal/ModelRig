from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


ENVELOPE_SCHEMA = "kaliv-agent3-memory-protection/v1"
WINDOWS_PROVIDER = "windows-dpapi-current-user"
KEY_SCOPE_CURRENT_USER = "current-user"
ENCODING_UTF8 = "utf-8"
PROTECTED_SENSITIVITIES = frozenset({"private", "secret"})
PROTECTED_FIELDS = frozenset({"value", "source_ref"})
MAX_PLAINTEXT_BYTES = 96_000
MAX_CIPHERTEXT_BYTES = 256_000
MAX_ENVELOPE_BYTES = 384_000

_ENVELOPE_KEYS = {
    "schema",
    "provider",
    "key_scope",
    "encoding",
    "scope_sha256",
    "ciphertext_sha256",
    "ciphertext_b64",
}


class MemoryProtectionError(RuntimeError):
    """A protected memory field cannot be safely encoded or opened."""


class MemoryProtectionProvider(Protocol):
    provider_id: str
    key_scope: str

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        ...

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        ...


@dataclass(frozen=True)
class MemoryProtectionScope:
    """Exact row/field context bound into the provider's authenticated scope."""

    memory_id: str
    subject: str
    predicate: str
    sensitivity: str
    field: str = "value"
    row_schema_version: int = 1

    def __post_init__(self) -> None:
        _bounded_text("memory_id", self.memory_id, 100)
        _bounded_text("subject", self.subject, 200)
        _bounded_text("predicate", self.predicate, 200)
        if self.sensitivity not in PROTECTED_SENSITIVITIES:
            raise MemoryProtectionError(
                f"sensitivity {self.sensitivity!r} is not a protected memory class"
            )
        if self.field not in PROTECTED_FIELDS:
            raise MemoryProtectionError(f"unsupported protected field: {self.field!r}")
        if (
            isinstance(self.row_schema_version, bool)
            or not isinstance(self.row_schema_version, int)
            or self.row_schema_version < 1
            or self.row_schema_version > 1_000_000
        ):
            raise MemoryProtectionError("row_schema_version must be a positive integer")

    def canonical_bytes(self) -> bytes:
        return _canonical_json(
            {
                "namespace": "agent3-memory-field",
                "memory_id": self.memory_id,
                "subject": self.subject,
                "predicate": self.predicate,
                "sensitivity": self.sensitivity,
                "field": self.field,
                "row_schema_version": self.row_schema_version,
            }
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def entropy(self) -> bytes:
        return hashlib.sha256(
            ENVELOPE_SCHEMA.encode("ascii") + b"\x00" + self.canonical_bytes()
        ).digest()


class MemoryProtectionCodec:
    """Strict versioned envelope around an injected OS protection provider.

    This module is deliberately storage-agnostic. It does not migrate SQLite,
    choose which API caller may read a value, log plaintext, create embeddings or
    activate Agent 3 memory. A later store integration must call it only at the
    authorized memory boundary.
    """

    def __init__(self, provider: MemoryProtectionProvider):
        provider_id = getattr(provider, "provider_id", None)
        key_scope = getattr(provider, "key_scope", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise MemoryProtectionError("provider_id is missing")
        if not isinstance(key_scope, str) or not key_scope.strip():
            raise MemoryProtectionError("provider key_scope is missing")
        self.provider = provider

    def protect_text(self, plaintext: str, *, scope: MemoryProtectionScope) -> str:
        if not isinstance(plaintext, str):
            raise MemoryProtectionError("protected memory plaintext must be text")
        if not plaintext:
            raise MemoryProtectionError("protected memory plaintext must not be empty")
        try:
            clear = plaintext.encode(ENCODING_UTF8, errors="strict")
        except UnicodeEncodeError as exc:
            raise MemoryProtectionError("protected memory plaintext is not valid UTF-8") from exc
        if len(clear) > MAX_PLAINTEXT_BYTES:
            raise MemoryProtectionError(
                f"protected memory plaintext exceeds {MAX_PLAINTEXT_BYTES} bytes"
            )

        clear_for_wipe = bytearray(clear)
        try:
            ciphertext = self.provider.protect(bytes(clear_for_wipe), entropy=scope.entropy())
        except MemoryProtectionError:
            raise
        except Exception as exc:
            raise MemoryProtectionError("memory protection provider failed") from exc
        finally:
            _wipe(clear_for_wipe)

        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise MemoryProtectionError("memory protection provider returned no ciphertext")
        if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise MemoryProtectionError(
                f"protected memory ciphertext exceeds {MAX_CIPHERTEXT_BYTES} bytes"
            )

        envelope = {
            "schema": ENVELOPE_SCHEMA,
            "provider": self.provider.provider_id,
            "key_scope": self.provider.key_scope,
            "encoding": ENCODING_UTF8,
            "scope_sha256": scope.sha256,
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        }
        encoded = _canonical_json(envelope).decode("utf-8")
        if len(encoded.encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise MemoryProtectionError(
                f"protected memory envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
            )
        return encoded

    def unprotect_text(self, envelope: str, *, scope: MemoryProtectionScope) -> str:
        value = parse_envelope(envelope)
        if value["provider"] != self.provider.provider_id:
            raise MemoryProtectionError("protected memory provider mismatch")
        if value["key_scope"] != self.provider.key_scope:
            raise MemoryProtectionError("protected memory key scope mismatch")
        if value["scope_sha256"] != scope.sha256:
            raise MemoryProtectionError("protected memory row/field scope mismatch")

        try:
            ciphertext = base64.b64decode(value["ciphertext_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise MemoryProtectionError("protected memory ciphertext is not valid base64") from exc
        if not ciphertext or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise MemoryProtectionError("protected memory ciphertext size is invalid")
        if hashlib.sha256(ciphertext).hexdigest() != value["ciphertext_sha256"]:
            raise MemoryProtectionError("protected memory ciphertext digest mismatch")

        encrypted_for_wipe = bytearray(ciphertext)
        clear_for_wipe: bytearray | None = None
        try:
            try:
                clear = self.provider.unprotect(
                    bytes(encrypted_for_wipe), entropy=scope.entropy()
                )
            except MemoryProtectionError:
                raise
            except Exception as exc:
                raise MemoryProtectionError("memory protection provider could not open value") from exc
            if not isinstance(clear, bytes) or not clear or len(clear) > MAX_PLAINTEXT_BYTES:
                raise MemoryProtectionError("unprotected memory plaintext size is invalid")
            clear_for_wipe = bytearray(clear)
            try:
                return bytes(clear_for_wipe).decode(ENCODING_UTF8, errors="strict")
            except UnicodeDecodeError as exc:
                raise MemoryProtectionError(
                    "unprotected memory plaintext is not valid UTF-8"
                ) from exc
        finally:
            _wipe(encrypted_for_wipe)
            if clear_for_wipe is not None:
                _wipe(clear_for_wipe)

    def metadata(self, envelope: str) -> dict[str, Any]:
        value = parse_envelope(envelope)
        ciphertext_bytes = len(base64.b64decode(value["ciphertext_b64"], validate=True))
        return {
            "schema": value["schema"],
            "provider": value["provider"],
            "key_scope": value["key_scope"],
            "encoding": value["encoding"],
            "scope_sha256": value["scope_sha256"],
            "ciphertext_sha256": value["ciphertext_sha256"],
            "ciphertext_bytes": ciphertext_bytes,
        }


class WindowsDpapiMemoryProtectionProvider:
    """Windows DPAPI current-user provider with UI forbidden.

    DPAPI supplies authenticated encryption and binds the ciphertext to the
    current Windows user profile. The exact memory row/field scope is supplied as
    optional entropy, so moving an envelope to another row or sensitivity fails.
    """

    provider_id = WINDOWS_PROVIDER
    key_scope = KEY_SCOPE_CURRENT_USER
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _DESCRIPTION = "Kaliv Agent 3 protected memory"

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def __init__(self, *, os_name: str | None = None):
        self._os_name = os_name or os.name
        if self._os_name != "nt":
            raise MemoryProtectionError("Agent 3 memory protection requires Windows DPAPI")
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise MemoryProtectionError("Windows DPAPI is unavailable") from exc

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
    ) -> tuple["WindowsDpapiMemoryProtectionProvider._DATA_BLOB", Any]:
        if not value:
            raise MemoryProtectionError("DPAPI input must not be empty")
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        blob = cls._DATA_BLOB(
            len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        return blob, buffer

    def _output_bytes(self, output: _DATA_BLOB) -> bytes:
        if output.cbData <= 0 or not output.pbData:
            raise MemoryProtectionError("Windows DPAPI returned an empty value")
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
                error = ctypes.get_last_error()
                raise MemoryProtectionError(
                    f"Windows could not protect Agent 3 memory (error {error})"
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
                error = ctypes.get_last_error()
                raise MemoryProtectionError(
                    f"Windows could not unlock Agent 3 memory (error {error})"
                )
            return self._output_bytes(output)
        finally:
            ctypes.memset(source_buffer, 0, len(source_buffer))
            ctypes.memset(entropy_buffer, 0, len(entropy_buffer))


def parse_envelope(envelope: str) -> dict[str, str]:
    if not isinstance(envelope, str) or not envelope:
        raise MemoryProtectionError("protected memory envelope must be non-empty text")
    raw = envelope.encode("utf-8", errors="strict")
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise MemoryProtectionError(
            f"protected memory envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
        )
    try:
        value = json.loads(envelope)
    except json.JSONDecodeError as exc:
        raise MemoryProtectionError("protected memory envelope is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MemoryProtectionError("protected memory envelope must be a JSON object")
    actual_keys = set(value)
    if actual_keys != _ENVELOPE_KEYS:
        raise MemoryProtectionError(
            "protected memory envelope keys mismatch: "
            f"missing={sorted(_ENVELOPE_KEYS - actual_keys)}, "
            f"extra={sorted(actual_keys - _ENVELOPE_KEYS)}"
        )
    if value.get("schema") != ENVELOPE_SCHEMA:
        raise MemoryProtectionError("unsupported protected memory envelope schema")
    if not isinstance(value.get("provider"), str) or not value["provider"]:
        raise MemoryProtectionError("protected memory provider is invalid")
    if value.get("key_scope") != KEY_SCOPE_CURRENT_USER:
        raise MemoryProtectionError("unsupported protected memory key scope")
    if value.get("encoding") != ENCODING_UTF8:
        raise MemoryProtectionError("unsupported protected memory encoding")
    for key in ("scope_sha256", "ciphertext_sha256"):
        digest = value.get(key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise MemoryProtectionError(f"protected memory {key} is invalid")
    payload = value.get("ciphertext_b64")
    if not isinstance(payload, str) or not payload:
        raise MemoryProtectionError("protected memory ciphertext is missing")
    return {key: str(value[key]) for key in _ENVELOPE_KEYS}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _bounded_text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryProtectionError(f"{name} must be non-empty text")
    if len(value) > maximum:
        raise MemoryProtectionError(f"{name} exceeds {maximum} characters")
    return value


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
