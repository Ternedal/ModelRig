from __future__ import annotations

import hashlib
import hmac

from app.agent3.memory_protection import MemoryProtectionError, ProtectedPayload


class TestMemoryProtector:
    """Authenticated test-only protector; never imported by production code."""

    provider = "test-memory-protector"

    def __init__(self, key: bytes = b"modelrig-memory-test-key-v1", key_id: str = "test-key-v1"):
        self.key = key
        self.key_id = key_id

    def _stream(self, scope: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        counter = 0
        while len(result) < length:
            result.extend(
                hashlib.sha256(
                    self.key + b"stream" + scope + nonce + counter.to_bytes(4, "big")
                ).digest()
            )
            counter += 1
        return bytes(result[:length])

    def seal(self, plaintext: bytes, *, scope: bytes) -> ProtectedPayload:
        nonce = hashlib.sha256(self.key + b"nonce" + scope + plaintext).digest()[:16]
        stream = self._stream(scope, nonce, len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(self.key, scope + nonce + ciphertext, hashlib.sha256).digest()
        return ProtectedPayload(self.provider, self.key_id, nonce + tag + ciphertext)

    def open(self, payload: ProtectedPayload, *, scope: bytes) -> bytes:
        if payload.provider != self.provider or payload.key_id != self.key_id:
            raise MemoryProtectionError("test protector identity mismatch")
        if len(payload.ciphertext) < 48:
            raise MemoryProtectionError("test ciphertext is truncated")
        nonce = payload.ciphertext[:16]
        tag = payload.ciphertext[16:48]
        ciphertext = payload.ciphertext[48:]
        expected = hmac.new(self.key, scope + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("test ciphertext authentication failed")
        stream = self._stream(scope, nonce, len(ciphertext))
        return bytes(left ^ right for left, right in zip(ciphertext, stream))
