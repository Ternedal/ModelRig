from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request

from .memory_protected_api import (
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
    ProtectedMemoryApiGrant,
)

MEMORY_STORE_ENV = "KALIV_AGENT3_MEMORY_STORE"
MEMORY_API_SECRET_ENV = "KALIV_AGENT3_MEMORY_API_SECRET"
MEMORY_GRANT_HEADER = "X-Kaliv-Agent3-Memory-Grant"
MEMORY_GRANT_SCHEMA = "kaliv-agent3-memory-grant/v1"
_MEMORY_GRANT_DOMAIN = MEMORY_GRANT_SCHEMA.encode("ascii") + b"\x00"
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_EXPECTED_KEYS = {
    "schema",
    "nonce",
    "device_id",
    "action",
    "request_id",
    "method",
    "path",
    "issued_at",
    "expires_at",
}
Clock = Callable[[], float]


def memory_store_mode(value: str | None = None) -> str:
    raw = os.getenv(MEMORY_STORE_ENV, "") if value is None else value
    mode = raw.strip()
    if mode == "":
        return "legacy"
    if mode not in {"legacy", "protected"}:
        raise ProtectedMemoryApiAuthorizationError(
            f"{MEMORY_STORE_ENV} must be legacy or protected"
        )
    if mode != raw:
        raise ProtectedMemoryApiAuthorizationError(
            f"{MEMORY_STORE_ENV} must be canonical"
        )
    return mode


def protected_memory_secret(value: str | bytes | None = None) -> bytes:
    raw: str | bytes
    if value is None:
        raw = os.getenv(MEMORY_API_SECRET_ENV, "")
    else:
        raw = value
    secret = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    if len(secret) < 32 or len(secret) > 4_096:
        raise ProtectedMemoryApiAuthorizationError(
            f"{MEMORY_API_SECRET_ENV} must contain 32-4096 bytes"
        )
    return secret


def _decode_segment(value: Any, *, maximum: int, label: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {label} is malformed"
        )
    if _SEGMENT_RE.fullmatch(value) is None:
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {label} is malformed"
        )
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {label} is malformed"
        ) from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(canonical, value):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {label} is not canonical"
        )
    return decoded


def _strict_object(payload: bytes) -> dict[str, Any]:
    duplicates: list[str] = []

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant payload is invalid"
        ) from exc
    if duplicates or not isinstance(value, dict) or set(value) != _EXPECTED_KEYS:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant payload shape is invalid"
        )
    return value


def _canonical_text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    cleaned = value.strip()
    if (
        not cleaned
        or cleaned != value
        or len(cleaned) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    return cleaned


def _timestamp(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    return parsed


class GatewayProtectedMemoryAuthorizer:
    """Verify and consume backend-issued grants at the loopback worker boundary."""

    def __init__(self, secret: str | bytes, *, clock: Clock = time.time):
        self._secret = protected_memory_secret(secret)
        if not callable(clock):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory gateway authorizer requires a clock"
            )
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(
        cls,
        *,
        clock: Clock = time.time,
    ) -> "GatewayProtectedMemoryAuthorizer":
        return cls(protected_memory_secret(), clock=clock)

    def __call__(
        self,
        request: Request,
        action: ProtectedMemoryApiAction,
    ) -> ProtectedMemoryApiGrant:
        if not isinstance(action, ProtectedMemoryApiAction):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory action must be typed"
            )
        token = request.headers.get(MEMORY_GRANT_HEADER, "")
        if not token or len(token) > 8_192 or token != token.strip():
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory gateway grant is required"
            )
        parts = token.split(".")
        if len(parts) != 2:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant is malformed"
            )
        payload_part, signature_part = parts
        signature = _decode_segment(
            signature_part,
            maximum=128,
            label="signature",
        )
        if len(signature) != hashlib.sha256().digest_size:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant signature is malformed"
            )
        expected = hmac.new(
            self._secret,
            _MEMORY_GRANT_DOMAIN + payload_part.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, signature):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant signature is invalid"
            )
        payload = _decode_segment(
            payload_part,
            maximum=6_144,
            label="payload",
        )
        claims = _strict_object(payload)

        if claims["schema"] != MEMORY_GRANT_SCHEMA:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant schema is invalid"
            )
        nonce = _canonical_text("nonce", claims["nonce"], 128)
        if len(_decode_segment(nonce, maximum=128, label="nonce")) != 32:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant nonce is invalid"
            )
        device_id = _canonical_text("device id", claims["device_id"], 200)
        request_id = _canonical_text("request id", claims["request_id"], 200)
        method = _canonical_text("method", claims["method"], 16)
        path = _canonical_text("path", claims["path"], 1_000)
        if method != method.upper() or method != request.method.upper():
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant method mismatch"
            )
        if path != request.url.path:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant path mismatch"
            )
        if request_id != request.headers.get("X-Request-ID", ""):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant request mismatch"
            )
        try:
            granted_action = ProtectedMemoryApiAction(claims["action"])
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant action is invalid"
            ) from exc
        if granted_action is not action:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant action mismatch"
            )

        issued_at = _timestamp("issued_at", claims["issued_at"])
        expires_at = _timestamp("expires_at", claims["expires_at"])
        now = _timestamp("clock", self._clock())
        if issued_at > now + 5.0:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant is future-dated"
            )
        if issued_at < now - 120.0 or expires_at <= now:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant is expired"
            )
        if expires_at <= issued_at or expires_at - issued_at > 120.0:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant lifetime is invalid"
            )

        with self._lock:
            expired = [key for key, expiry in self._seen.items() if expiry <= now]
            for key in expired:
                self._seen.pop(key, None)
            if nonce in self._seen:
                raise ProtectedMemoryApiAuthorizationError(
                    "protected memory grant has already been consumed"
                )
            self._seen[nonce] = expires_at

        return ProtectedMemoryApiGrant(
            principal=f"device:{device_id}",
            action=granted_action,
            request_id=request_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
