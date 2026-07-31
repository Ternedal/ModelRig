#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protection import (  # noqa: E402
    ENVELOPE_SCHEMA,
    KEY_SCOPE_CURRENT_USER,
    MAX_PLAINTEXT_BYTES,
    MemoryProtectionCodec,
    MemoryProtectionError,
    MemoryProtectionScope,
    WindowsDpapiMemoryProtectionProvider,
    parse_envelope,
)


class TestAeadProvider:
    provider_id = "test-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-test-key-that-is-not-production"):
        self.key = key
        self.counter = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        block = 0
        while len(result) < length:
            result.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(result[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.counter += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.counter.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("test ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


class InvalidUtf8Provider(TestAeadProvider):
    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        super().unprotect(ciphertext, entropy=entropy)
        return b"\xff\xfe"


class EmptyCiphertextProvider(TestAeadProvider):
    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        return b""


class ExplodingProvider(TestAeadProvider):
    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        raise ValueError("raw provider detail")


checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_error(label: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except MemoryProtectionError as exc:
        check(label, contains is None or contains in str(exc))
    except Exception:
        check(label, False)
    else:
        check(label, False)


def scope(**changes) -> MemoryProtectionScope:
    values = {
        "memory_id": "memory-123",
        "subject": "Anders",
        "predicate": "private_note",
        "sensitivity": "private",
        "field": "value",
        "row_schema_version": 1,
    }
    values.update(changes)
    return MemoryProtectionScope(**values)


provider = TestAeadProvider()
codec = MemoryProtectionCodec(provider)
original = "Min følsomme værdi med æøå og 🔒"
envelope = codec.protect_text(original, scope=scope())
parsed = parse_envelope(envelope)

check("private value roundtrips", codec.unprotect_text(envelope, scope=scope()) == original)
check("envelope uses the exact versioned schema", parsed["schema"] == ENVELOPE_SCHEMA)
check("envelope is canonical compact JSON", envelope == json.dumps(json.loads(envelope), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
check("plaintext is absent from the envelope", original not in envelope and "følsomme" not in envelope)
check("envelope stores no row labels", all(value not in envelope for value in ("Anders", "private_note", "memory-123")))
check("ciphertext digest matches encoded bytes", hashlib.sha256(base64.b64decode(parsed["ciphertext_b64"])).hexdigest() == parsed["ciphertext_sha256"])
check("scope digest binds exact row context", parsed["scope_sha256"] == scope().sha256)

metadata = codec.metadata(envelope)
check("metadata exposes no ciphertext or plaintext", "ciphertext_b64" not in metadata and original not in json.dumps(metadata))
check("metadata reports bounded ciphertext bytes", isinstance(metadata["ciphertext_bytes"], int) and metadata["ciphertext_bytes"] > 0)

secret_scope = scope(sensitivity="secret", predicate="password_hint")
secret_envelope = codec.protect_text("kun lokalt", scope=secret_scope)
check("secret value roundtrips", codec.unprotect_text(secret_envelope, scope=secret_scope) == "kun lokalt")

source_scope = scope(field="source_ref")
source_envelope = codec.protect_text("import://private/source", scope=source_scope)
check("source_ref has its own protected scope", codec.unprotect_text(source_envelope, scope=source_scope) == "import://private/source")
expect_error(
    "ciphertext cannot move from value to source_ref",
    lambda: codec.unprotect_text(envelope, scope=source_scope),
    "scope mismatch",
)

for label, changed in (
    ("memory id", scope(memory_id="memory-456")),
    ("subject", scope(subject="Other")),
    ("predicate", scope(predicate="other_predicate")),
    ("sensitivity", scope(sensitivity="secret")),
    ("row schema version", scope(row_schema_version=2)),
):
    expect_error(
        f"wrong {label} scope fails closed",
        lambda changed=changed: codec.unprotect_text(envelope, scope=changed),
        "scope mismatch",
    )

expect_error(
    "public values are not accepted by the protected codec",
    lambda: scope(sensitivity="public"),
    "not a protected memory class",
)
expect_error(
    "operational values are not accepted by the protected codec",
    lambda: scope(sensitivity="operational"),
    "not a protected memory class",
)
expect_error(
    "unknown protected field is rejected",
    lambda: scope(field="embedding"),
    "unsupported protected field",
)
expect_error(
    "empty plaintext is rejected",
    lambda: codec.protect_text("", scope=scope()),
    "must not be empty",
)
expect_error(
    "oversized plaintext is rejected",
    lambda: codec.protect_text("x" * (MAX_PLAINTEXT_BYTES + 1), scope=scope()),
    "exceeds",
)


def changed_envelope(**changes) -> str:
    value = json.loads(envelope)
    value.update(changes)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


value_with_extra = json.loads(envelope)
value_with_extra["created_at"] = "2026-07-28T00:00:00Z"
expect_error(
    "unknown envelope fields are rejected",
    lambda: parse_envelope(json.dumps(value_with_extra)),
    "keys mismatch",
)
value_missing = json.loads(envelope)
del value_missing["scope_sha256"]
expect_error(
    "missing envelope fields are rejected",
    lambda: parse_envelope(json.dumps(value_missing)),
    "keys mismatch",
)
expect_error(
    "unknown schema is rejected",
    lambda: parse_envelope(changed_envelope(schema="kaliv-agent3-memory-protection/v2")),
    "unsupported",
)
expect_error(
    "unknown key scope is rejected",
    lambda: parse_envelope(changed_envelope(key_scope="machine")),
    "key scope",
)
expect_error(
    "unknown encoding is rejected",
    lambda: parse_envelope(changed_envelope(encoding="utf-16")),
    "encoding",
)
expect_error(
    "invalid scope digest is rejected",
    lambda: parse_envelope(changed_envelope(scope_sha256="x" * 64)),
    "scope_sha256",
)
expect_error(
    "invalid ciphertext digest is rejected",
    lambda: parse_envelope(changed_envelope(ciphertext_sha256="0" * 63)),
    "ciphertext_sha256",
)
expect_error(
    "invalid JSON is rejected",
    lambda: parse_envelope("{not-json"),
    "invalid JSON",
)
expect_error(
    "non-object JSON is rejected",
    lambda: parse_envelope("[]"),
    "JSON object",
)

other_codec = MemoryProtectionCodec(TestAeadProvider(key=b"another-t033-test-key-material"))
expect_error(
    "ciphertext cannot be opened with another provider key",
    lambda: other_codec.unprotect_text(envelope, scope=scope()),
    "authentication failed",
)
wrong_provider = TestAeadProvider()
wrong_provider.provider_id = "another-provider"
expect_error(
    "provider identity drift is rejected before decryption",
    lambda: MemoryProtectionCodec(wrong_provider).unprotect_text(envelope, scope=scope()),
    "provider mismatch",
)

ciphertext = bytearray(base64.b64decode(parsed["ciphertext_b64"]))
ciphertext[-1] ^= 1
tampered_b64 = base64.b64encode(ciphertext).decode("ascii")
expect_error(
    "ciphertext tamper with stale digest is rejected",
    lambda: codec.unprotect_text(changed_envelope(ciphertext_b64=tampered_b64), scope=scope()),
    "digest mismatch",
)
tampered_digest = hashlib.sha256(ciphertext).hexdigest()
expect_error(
    "ciphertext tamper with rewritten digest still fails provider authentication",
    lambda: codec.unprotect_text(
        changed_envelope(
            ciphertext_b64=tampered_b64,
            ciphertext_sha256=tampered_digest,
        ),
        scope=scope(),
    ),
    "authentication failed",
)
expect_error(
    "invalid base64 is rejected",
    lambda: codec.unprotect_text(changed_envelope(ciphertext_b64="%%%"), scope=scope()),
    "base64",
)
expect_error(
    "invalid UTF-8 from provider fails closed",
    lambda: MemoryProtectionCodec(InvalidUtf8Provider()).unprotect_text(
        MemoryProtectionCodec(InvalidUtf8Provider()).protect_text("ok", scope=scope()),
        scope=scope(),
    ),
    "valid UTF-8",
)
expect_error(
    "empty provider ciphertext is rejected",
    lambda: MemoryProtectionCodec(EmptyCiphertextProvider()).protect_text("value", scope=scope()),
    "no ciphertext",
)
expect_error(
    "provider internals are normalized",
    lambda: MemoryProtectionCodec(ExplodingProvider()).protect_text("value", scope=scope()),
    "provider failed",
)
expect_error(
    "non-Windows provider construction fails closed",
    lambda: WindowsDpapiMemoryProtectionProvider(os_name="posix"),
    "requires Windows DPAPI",
)

if os.name == "nt":
    dpapi = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())
    dpapi_envelope = dpapi.protect_text(original, scope=scope())
    check("Windows DPAPI current-user roundtrip", dpapi.unprotect_text(dpapi_envelope, scope=scope()) == original)
    dpapi_value = json.loads(dpapi_envelope)
    dpapi_cipher = bytearray(base64.b64decode(dpapi_value["ciphertext_b64"]))
    dpapi_cipher[-1] ^= 1
    dpapi_value["ciphertext_b64"] = base64.b64encode(dpapi_cipher).decode("ascii")
    dpapi_value["ciphertext_sha256"] = hashlib.sha256(dpapi_cipher).hexdigest()
    expect_error(
        "Windows DPAPI rejects authenticated ciphertext tamper",
        lambda: dpapi.unprotect_text(
            json.dumps(dpapi_value, sort_keys=True, separators=(",", ":")),
            scope=scope(),
        ),
        "could not unlock",
    )
else:
    check("Windows DPAPI live contract is reserved for the Windows CI job", True)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 MEMORY PROTECTION: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
