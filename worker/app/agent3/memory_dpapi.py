from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol

from .memory_protection import MemoryProtectionError, ProtectedPayload

PROVIDER = "windows-dpapi-current-user"
KEY_ID = "current-user:v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DpapiBackend(Protocol):
    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _BlobBuffer:
    """Mutable DATA_BLOB input whose bytes are wiped after the native call."""

    def __init__(self, value: bytes):
        if not isinstance(value, bytes):
            raise MemoryProtectionError("DPAPI input must be bytes")
        self._mutable = bytearray(value)
        if self._mutable:
            self._array = (ctypes.c_ubyte * len(self._mutable)).from_buffer(self._mutable)
            pointer = ctypes.cast(self._array, ctypes.POINTER(ctypes.c_ubyte))
        else:
            self._array = None
            pointer = ctypes.POINTER(ctypes.c_ubyte)()
        self.blob = _DataBlob(len(self._mutable), pointer)

    def wipe(self) -> None:
        self._mutable[:] = b"\x00" * len(self._mutable)


class CtypesWindowsDpapiBackend:
    """Minimal current-user DPAPI binding with caller-supplied optional entropy."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise MemoryProtectionError("Windows DPAPI is unavailable on this platform")
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (OSError, AttributeError) as exc:
            raise MemoryProtectionError("Windows DPAPI libraries are unavailable") from exc

        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _error(operation: str) -> MemoryProtectionError:
        code = ctypes.get_last_error()
        detail = ctypes.FormatError(code).strip() if code else "unknown Windows error"
        return MemoryProtectionError(f"Windows DPAPI {operation} failed ({code}): {detail}")

    def _copy_and_free(self, output: _DataBlob) -> bytes:
        if not output.pbData or output.cbData == 0:
            if output.pbData:
                self._kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))
            raise MemoryProtectionError("Windows DPAPI returned empty output")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        if not plaintext:
            raise MemoryProtectionError("Windows DPAPI refuses empty plaintext")
        clear = _BlobBuffer(plaintext)
        scope = _BlobBuffer(entropy)
        output = _DataBlob()
        try:
            ok = self._crypt32.CryptProtectData(
                ctypes.byref(clear.blob),
                "Kaliv Agent 3 memory",
                ctypes.byref(scope.blob),
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not ok:
                raise self._error("protect")
            return self._copy_and_free(output)
        finally:
            clear.wipe()
            scope.wipe()

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if not ciphertext:
            raise MemoryProtectionError("Windows DPAPI ciphertext is empty")
        encrypted = _BlobBuffer(ciphertext)
        scope = _BlobBuffer(entropy)
        output = _DataBlob()
        description = wintypes.LPWSTR()
        try:
            ok = self._crypt32.CryptUnprotectData(
                ctypes.byref(encrypted.blob),
                ctypes.byref(description),
                ctypes.byref(scope.blob),
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not ok:
                raise self._error("unprotect")
            return self._copy_and_free(output)
        finally:
            if description:
                self._kernel32.LocalFree(ctypes.cast(description, wintypes.HLOCAL))
            encrypted.wipe()
            scope.wipe()


class WindowsDpapiMemoryProtector:
    """MemoryProtector backed by current-user Windows DPAPI.

    No machine-scope flag is supplied. The exact protected-envelope scope is
    passed as optional entropy, binding ciphertext to store, record and field in
    addition to the current Windows user. A backend may be injected only for
    platform-independent contract tests; production lazily constructs the real
    Windows binding and never falls back to plaintext.
    """

    provider = PROVIDER
    key_id = KEY_ID

    def __init__(
        self,
        backend: DpapiBackend | None = None,
        *,
        platform_name: str | None = None,
    ) -> None:
        self._backend = backend
        self._platform_name = os.name if platform_name is None else platform_name

    def _require_backend(self) -> DpapiBackend:
        if self._backend is not None:
            return self._backend
        if self._platform_name != "nt":
            raise MemoryProtectionError("sensitive memory storage requires Windows DPAPI")
        self._backend = CtypesWindowsDpapiBackend()
        return self._backend

    def seal(self, plaintext: bytes, *, scope: bytes) -> ProtectedPayload:
        if not isinstance(scope, bytes) or not scope:
            raise MemoryProtectionError("DPAPI memory scope is missing")
        try:
            ciphertext = self._require_backend().protect(plaintext, entropy=scope)
        except MemoryProtectionError:
            raise
        except Exception as exc:
            raise MemoryProtectionError(
                f"Windows DPAPI protect failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise MemoryProtectionError("Windows DPAPI returned invalid ciphertext")
        return ProtectedPayload(
            provider=self.provider,
            key_id=self.key_id,
            ciphertext=ciphertext,
        )

    def open(self, payload: ProtectedPayload, *, scope: bytes) -> bytes:
        if payload.provider != self.provider or payload.key_id != self.key_id:
            raise MemoryProtectionError("protected memory provider or key id is unsupported")
        if not isinstance(scope, bytes) or not scope:
            raise MemoryProtectionError("DPAPI memory scope is missing")
        try:
            plaintext = self._require_backend().unprotect(
                payload.ciphertext,
                entropy=scope,
            )
        except MemoryProtectionError:
            raise
        except Exception as exc:
            raise MemoryProtectionError(
                f"Windows DPAPI unprotect failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(plaintext, bytes):
            raise MemoryProtectionError("Windows DPAPI returned invalid plaintext")
        return plaintext
