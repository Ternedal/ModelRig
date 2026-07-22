#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.memory_dpapi import (  # noqa: E402
    KEY_ID,
    PROVIDER,
    WindowsDpapiMemoryProtector,
)
from app.agent3.memory_protection import (  # noqa: E402
    PREFIX,
    MemoryProtectionError,
    ProtectedPayload,
    open_text,
    parse_envelope,
    seal_text,
)


class AuthenticatedBackend:
    """Contract double proving exact scope forwarding without Windows."""

    def __init__(self):
        self.key = b"dpapi-contract-test-key"
        self.last_protect_entropy = None
        self.last_unprotect_entropy = None

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.last_protect_entropy = entropy
        tag = hmac.new(self.key, entropy + plaintext, hashlib.sha256).digest()
        return tag + plaintext[::-1]

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        self.last_unprotect_entropy = entropy
        if len(ciphertext) < 32:
            raise MemoryProtectionError("contract ciphertext is truncated")
        tag, reversed_plaintext = ciphertext[:32], ciphertext[32:]
        plaintext = reversed_plaintext[::-1]
        expected = hmac.new(self.key, entropy + plaintext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("contract scope authentication failed")
        return plaintext


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


def rewrite_scope(envelope: str, *, store_scope: str) -> str:
    raw = json.loads(envelope[len(PREFIX) :])
    raw["store_scope"] = store_scope
    return PREFIX + json.dumps(raw, sort_keys=True, separators=(",", ":"))


identity = {
    "store_scope": "store-dpapi-test",
    "record_id": "memory-dpapi-test",
    "field": "value",
}
secret = "T-033 følsom memoryværdi"
backend = AuthenticatedBackend()
protector = WindowsDpapiMemoryProtector(backend=backend, platform_name="contract-test")
envelope = seal_text(protector, secret, **identity)
parsed = parse_envelope(envelope)
check(parsed.provider == PROVIDER, "envelope records the Windows DPAPI provider")
check(parsed.key_id == KEY_ID, "envelope records the current-user key version")
check(secret not in envelope, "contract envelope contains no readable plaintext")
check(open_text(protector, envelope, **identity) == secret, "injected backend roundtrip succeeds")
check(
    backend.last_protect_entropy == backend.last_unprotect_entropy
    and backend.last_protect_entropy is not None,
    "the exact protected scope is forwarded as DPAPI entropy",
)

wrong_metadata = rewrite_scope(envelope, store_scope="other-store")
rejects(
    lambda: open_text(
        protector,
        wrong_metadata,
        store_scope="other-store",
        record_id=identity["record_id"],
        field=identity["field"],
    ),
    "metadata copied to another scope fails backend authentication",
)
rejects(
    lambda: protector.open(
        ProtectedPayload("other-provider", KEY_ID, parsed.ciphertext),
        scope=backend.last_protect_entropy,
    ),
    "unknown provider is rejected before unprotect",
)
rejects(
    lambda: protector.open(
        ProtectedPayload(PROVIDER, "future-key", parsed.ciphertext),
        scope=backend.last_protect_entropy,
    ),
    "unknown key id is rejected before unprotect",
)

if os.name != "nt":
    locked = WindowsDpapiMemoryProtector(platform_name=os.name)
    rejects(
        lambda: locked.seal(b"must-not-fallback", scope=b"scope"),
        "non-Windows production use fails closed without a fallback",
    )
    print("  INFO: real DPAPI checks are reserved for windows-latest")
else:
    real = WindowsDpapiMemoryProtector()
    real_envelope = seal_text(real, secret, **identity)
    check(secret not in real_envelope, "real DPAPI envelope contains no plaintext")
    check(open_text(real, real_envelope, **identity) == secret, "real current-user DPAPI roundtrip succeeds")

    real_wrong_scope = rewrite_scope(real_envelope, store_scope="restored-other-scope")
    rejects(
        lambda: open_text(
            real,
            real_wrong_scope,
            store_scope="restored-other-scope",
            record_id=identity["record_id"],
            field=identity["field"],
        ),
        "real DPAPI optional entropy rejects a copied store scope",
    )

    raw = json.loads(real_envelope[len(PREFIX) :])
    ciphertext = bytearray(base64.b64decode(raw["ciphertext"]))
    ciphertext[-1] ^= 1
    raw["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
    corrupted = PREFIX + json.dumps(raw, sort_keys=True, separators=(",", ":"))
    rejects(
        lambda: open_text(real, corrupted, **identity),
        "real DPAPI rejects corrupted ciphertext",
    )

print(f"\n===== MEMORY WINDOWS DPAPI: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
