#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.memory_protection import (  # noqa: E402
    PREFIX,
    MemoryProtectionError,
    ProtectedPayload,
    is_protected,
    open_text,
    parse_envelope,
    rewrap_text,
    seal_text,
)


class FakeScopedProtector:
    """Authenticated reversible test double. Never used by production code."""

    provider = "test-scoped"

    def __init__(self, key: bytes, key_id: str):
        self.key = key
        self.key_id = key_id

    def _stream(self, scope: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(
                hashlib.sha256(
                    self.key + b"stream" + scope + nonce + counter.to_bytes(4, "big")
                ).digest()
            )
            counter += 1
        return bytes(output[:length])

    def seal(self, plaintext: bytes, *, scope: bytes) -> ProtectedPayload:
        nonce = hashlib.sha256(self.key + b"nonce" + scope + plaintext).digest()[:16]
        stream = self._stream(scope, nonce, len(plaintext))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
        tag = hmac.new(self.key, scope + nonce + ciphertext, hashlib.sha256).digest()
        return ProtectedPayload(self.provider, self.key_id, nonce + tag + ciphertext)

    def open(self, payload: ProtectedPayload, *, scope: bytes) -> bytes:
        if payload.provider != self.provider or payload.key_id != self.key_id:
            raise MemoryProtectionError("wrong test protector")
        if len(payload.ciphertext) < 48:
            raise MemoryProtectionError("truncated test ciphertext")
        nonce = payload.ciphertext[:16]
        tag = payload.ciphertext[16:48]
        ciphertext = payload.ciphertext[48:]
        expected = hmac.new(self.key, scope + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("test authentication failed")
        stream = self._stream(scope, nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream))


passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejects(fn, message: str) -> None:
    try:
        fn()
    except MemoryProtectionError:
        check(True, message)
    else:
        check(False, message)


old = FakeScopedProtector(b"old-key-material-32-bytes-long!!!", "old-key")
new = FakeScopedProtector(b"new-key-material-32-bytes-long!!!", "new-key")
secret = "Mit hemmelige telefonnummer er 12 34 56 78"
identity = {
    "store_scope": "store-7abf",
    "record_id": "memory-123",
    "field": "value",
}

envelope = seal_text(old, secret, **identity)
check(is_protected(envelope), "sealed text has the protected envelope prefix")
check(secret not in envelope, "stored envelope contains no readable plaintext")
check(open_text(old, envelope, **identity) == secret, "roundtrip opens in the exact scope")
parsed = parse_envelope(envelope)
check(parsed.schema == "kaliv-memory-protected/v1", "schema is explicit and versioned")
check(parsed.provider == "test-scoped" and parsed.key_id == "old-key", "provider and key id are retained")

rejects(
    lambda: open_text(old, envelope, **{**identity, "store_scope": "other-store"}),
    "ciphertext copied to another store scope is rejected",
)
rejects(
    lambda: open_text(old, envelope, **{**identity, "record_id": "memory-999"}),
    "ciphertext copied to another memory record is rejected",
)
rejects(
    lambda: open_text(old, envelope, **{**identity, "field": "source_ref"}),
    "ciphertext copied to another field is rejected",
)
rejects(lambda: open_text(new, envelope, **identity), "wrong key id/protector is rejected")

raw = json.loads(envelope[len(PREFIX) :])
raw["schema"] = "kaliv-memory-protected/v99"
rejects(
    lambda: parse_envelope(PREFIX + json.dumps(raw, sort_keys=True)),
    "unknown envelope schema is rejected",
)
raw = json.loads(envelope[len(PREFIX) :])
raw["unexpected"] = True
rejects(
    lambda: parse_envelope(PREFIX + json.dumps(raw, sort_keys=True)),
    "unknown envelope fields are rejected",
)
raw = json.loads(envelope[len(PREFIX) :])
raw["ciphertext"] = "***not-base64***"
rejects(
    lambda: parse_envelope(PREFIX + json.dumps(raw, sort_keys=True)),
    "invalid base64 is rejected",
)
raw = json.loads(envelope[len(PREFIX) :])
cipher = bytearray(base64.b64decode(raw["ciphertext"]))
cipher[-1] ^= 1
raw["ciphertext"] = base64.b64encode(cipher).decode("ascii")
tampered = PREFIX + json.dumps(raw, sort_keys=True, separators=(",", ":"))
rejects(lambda: open_text(old, tampered, **identity), "ciphertext corruption is authenticated and rejected")
rejects(lambda: parse_envelope("plain text"), "plaintext is never mistaken for an envelope")

rotated = rewrap_text(old, new, envelope, **identity)
check(secret not in rotated, "rotated envelope still contains no plaintext")
check(parse_envelope(rotated).key_id == "new-key", "rotation records the new key id")
check(open_text(new, rotated, **identity) == secret, "rotated envelope opens with the new protector")
rejects(lambda: open_text(old, rotated, **identity), "rotated envelope no longer opens with the old key")

print(f"\n===== MEMORY PROTECTION ENVELOPE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
