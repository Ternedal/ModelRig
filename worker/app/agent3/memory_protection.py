from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

SCHEMA = "kaliv-memory-protected/v1"
PREFIX = "kaliv-protected:"
_ALLOWED_FIELDS = {"value", "source_ref"}
_MAX_ENVELOPE_CHARS = 100_000


class MemoryProtectionError(RuntimeError):
    """Protected memory could not be safely sealed, validated or opened."""


@dataclass(frozen=True)
class ProtectedPayload:
    provider: str
    key_id: str
    ciphertext: bytes


class MemoryProtector(Protocol):
    """OS-backed protection boundary.

    Implementations must authenticate ``scope`` as associated data (or the OS
    equivalent) so ciphertext copied to another store, record or field cannot be
    opened. This module deliberately provides no plaintext/no-op fallback.
    """

    def seal(self, plaintext: bytes, *, scope: bytes) -> ProtectedPayload: ...

    def open(self, payload: ProtectedPayload, *, scope: bytes) -> bytes: ...


@dataclass(frozen=True)
class ProtectedEnvelope:
    schema: str
    store_scope: str
    record_id: str
    field: str
    provider: str
    key_id: str
    ciphertext: bytes


def is_protected(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _clean_token(name: str, value: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MemoryProtectionError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise MemoryProtectionError(f"invalid {name}")
    return cleaned


def _validated_identity(
    *, store_scope: str, record_id: str, field: str
) -> tuple[str, str, str]:
    store_scope = _clean_token("store_scope", store_scope, 200)
    record_id = _clean_token("record_id", record_id, 100)
    if field not in _ALLOWED_FIELDS:
        raise MemoryProtectionError(f"invalid protected field: {field!r}")
    return store_scope, record_id, field


def protection_scope(*, store_scope: str, record_id: str, field: str) -> bytes:
    store_scope, record_id, field = _validated_identity(
        store_scope=store_scope, record_id=record_id, field=field
    )
    return json.dumps(
        {
            "schema": SCHEMA,
            "store_scope": store_scope,
            "record_id": record_id,
            "field": field,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def seal_text(
    protector: MemoryProtector,
    plaintext: str,
    *,
    store_scope: str,
    record_id: str,
    field: str,
) -> str:
    if not isinstance(plaintext, str):
        raise MemoryProtectionError("protected plaintext must be text")
    store_scope, record_id, field = _validated_identity(
        store_scope=store_scope, record_id=record_id, field=field
    )
    scope = protection_scope(
        store_scope=store_scope, record_id=record_id, field=field
    )
    try:
        payload = protector.seal(plaintext.encode("utf-8"), scope=scope)
    except MemoryProtectionError:
        raise
    except Exception as exc:
        raise MemoryProtectionError(
            f"memory protector seal failed: {type(exc).__name__}"
        ) from exc
    provider = _clean_token("provider", payload.provider, 100)
    key_id = _clean_token("key_id", payload.key_id, 200)
    if not isinstance(payload.ciphertext, bytes) or not payload.ciphertext:
        raise MemoryProtectionError("protector returned empty ciphertext")
    envelope = {
        "ciphertext": base64.b64encode(payload.ciphertext).decode("ascii"),
        "field": field,
        "key_id": key_id,
        "provider": provider,
        "record_id": record_id,
        "schema": SCHEMA,
        "store_scope": store_scope,
    }
    encoded = PREFIX + json.dumps(
        envelope,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > _MAX_ENVELOPE_CHARS:
        raise MemoryProtectionError("protected envelope is too large")
    return encoded


def parse_envelope(value: str) -> ProtectedEnvelope:
    if not is_protected(value):
        raise MemoryProtectionError("value is not a protected memory envelope")
    if len(value) > _MAX_ENVELOPE_CHARS:
        raise MemoryProtectionError("protected envelope is too large")
    try:
        raw = json.loads(value[len(PREFIX) :])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MemoryProtectionError("protected envelope is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise MemoryProtectionError("protected envelope must be an object")
    required = {
        "schema",
        "store_scope",
        "record_id",
        "field",
        "provider",
        "key_id",
        "ciphertext",
    }
    if set(raw) != required:
        raise MemoryProtectionError("protected envelope fields are invalid")
    if raw.get("schema") != SCHEMA:
        raise MemoryProtectionError("unknown protected memory schema")
    store_scope, record_id, field = _validated_identity(
        store_scope=raw.get("store_scope"),
        record_id=raw.get("record_id"),
        field=raw.get("field"),
    )
    provider = _clean_token("provider", raw.get("provider"), 100)
    key_id = _clean_token("key_id", raw.get("key_id"), 200)
    ciphertext_text = raw.get("ciphertext")
    if not isinstance(ciphertext_text, str) or not ciphertext_text:
        raise MemoryProtectionError("protected ciphertext is missing")
    try:
        ciphertext = base64.b64decode(ciphertext_text, validate=True)
    except (ValueError, TypeError) as exc:
        raise MemoryProtectionError("protected ciphertext is not valid base64") from exc
    if not ciphertext:
        raise MemoryProtectionError("protected ciphertext is empty")
    return ProtectedEnvelope(
        schema=SCHEMA,
        store_scope=store_scope,
        record_id=record_id,
        field=field,
        provider=provider,
        key_id=key_id,
        ciphertext=ciphertext,
    )


def open_text(
    protector: MemoryProtector,
    value: str,
    *,
    store_scope: str,
    record_id: str,
    field: str,
) -> str:
    expected_scope, expected_record, expected_field = _validated_identity(
        store_scope=store_scope, record_id=record_id, field=field
    )
    envelope = parse_envelope(value)
    if (
        envelope.store_scope != expected_scope
        or envelope.record_id != expected_record
        or envelope.field != expected_field
    ):
        raise MemoryProtectionError("protected memory scope mismatch")
    scope = protection_scope(
        store_scope=expected_scope,
        record_id=expected_record,
        field=expected_field,
    )
    try:
        plaintext = protector.open(
            ProtectedPayload(
                provider=envelope.provider,
                key_id=envelope.key_id,
                ciphertext=envelope.ciphertext,
            ),
            scope=scope,
        )
    except MemoryProtectionError:
        raise
    except Exception as exc:
        raise MemoryProtectionError(
            f"memory protector open failed: {type(exc).__name__}"
        ) from exc
    if not isinstance(plaintext, bytes):
        raise MemoryProtectionError("memory protector returned non-bytes plaintext")
    try:
        return plaintext.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MemoryProtectionError("protected plaintext is not valid UTF-8") from exc


def rewrap_text(
    old_protector: MemoryProtector,
    new_protector: MemoryProtector,
    value: str,
    *,
    store_scope: str,
    record_id: str,
    field: str,
) -> str:
    plaintext = open_text(
        old_protector,
        value,
        store_scope=store_scope,
        record_id=record_id,
        field=field,
    )
    return seal_text(
        new_protector,
        plaintext,
        store_scope=store_scope,
        record_id=record_id,
        field=field,
    )
