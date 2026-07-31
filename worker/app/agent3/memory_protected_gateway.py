from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request

from .memory_protected_api import (
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
    ProtectedMemoryApiGrant,
)

MEMORY_STORE_ENV = "KALIV_AGENT3_MEMORY_STORE"
MEMORY_API_SECRET_ENV = "KALIV_AGENT3_MEMORY_API_SECRET"
MEMORY_GRANT_DB_ENV = "KALIV_AGENT3_MEMORY_GRANT_DB"
MEMORY_GRANT_HEADER = "X-Kaliv-Agent3-Memory-Grant"
MEMORY_STORE_ATTESTATION_HEADER = "X-Kaliv-Agent3-Memory-Store"
MEMORY_STORE_ATTESTATION_VALUE = "protected"
MEMORY_GRANT_SCHEMA = "kaliv-agent3-memory-grant/v1"
MEMORY_REQUEST_BODY_MAX_BYTES = 64 * 1024
_MEMORY_GRANT_DOMAIN = MEMORY_GRANT_SCHEMA.encode("ascii") + b"\x00"
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_KEYS = {
    "schema",
    "nonce",
    "device_id",
    "action",
    "request_id",
    "method",
    "path",
    "query",
    "body_sha256",
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


def protected_memory_grant_db(value: str | Path | None = None) -> Path:
    raw = os.getenv(MEMORY_GRANT_DB_ENV, "") if value is None else os.fspath(value)
    if not isinstance(raw, str):
        raise ProtectedMemoryApiAuthorizationError(
            f"{MEMORY_GRANT_DB_ENV} must be a path"
        )
    cleaned = raw.strip()
    if not cleaned or cleaned != raw or "\x00" in cleaned:
        raise ProtectedMemoryApiAuthorizationError(
            f"{MEMORY_GRANT_DB_ENV} must be a canonical non-empty path"
        )
    path = Path(cleaned)
    if path.exists() and path.is_symlink():
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant ledger must not be a symlink"
        )
    parent = path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant ledger parent is invalid"
        )
    parent.mkdir(parents=True, exist_ok=True)
    return path


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


def _canonical_text(name: str, value: Any, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    cleaned = value.strip()
    if (
        (not allow_empty and not cleaned)
        or (value and cleaned != value)
        or len(value) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    return value


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


class ProtectedMemoryGrantReplayLedger:
    """Durable single-use ledger for write grants; stores hashes only."""

    def __init__(self, path: str | Path):
        self.path = protected_memory_grant_db(path)
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS protected_memory_grant_uses (
                    nonce_sha256 TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    device_sha256 TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    consumed_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_protected_memory_grant_expiry
                    ON protected_memory_grant_uses(expires_at);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def consume(
        self,
        *,
        nonce: str,
        action: ProtectedMemoryApiAction,
        device_id: str,
        request_id: str,
        now: float,
        expires_at: float,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM protected_memory_grant_uses WHERE expires_at <= ?",
                (now,),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO protected_memory_grant_uses(
                        nonce_sha256,action,device_sha256,request_sha256,
                        consumed_at,expires_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        self._digest(nonce),
                        action.value,
                        self._digest(device_id),
                        self._digest(request_id),
                        now,
                        expires_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ProtectedMemoryApiAuthorizationError(
                    "protected memory grant has already been consumed"
                ) from exc
            connection.commit()
        except ProtectedMemoryApiAuthorizationError:
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory write grant could not be consumed durably"
            ) from exc
        finally:
            connection.close()


class GatewayProtectedMemoryAuthorizer:
    """Verify backend-issued grants at the loopback worker boundary."""

    def __init__(
        self,
        secret: str | bytes,
        *,
        replay_ledger: ProtectedMemoryGrantReplayLedger,
        clock: Clock = time.time,
    ):
        self._secret = protected_memory_secret(secret)
        if not isinstance(replay_ledger, ProtectedMemoryGrantReplayLedger):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory gateway authorizer requires a durable replay ledger"
            )
        self._replay_ledger = replay_ledger
        if not callable(clock):
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory gateway authorizer requires a clock"
            )
        self._clock = clock
        self._seen_reads: dict[str, float] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(
        cls,
        *,
        replay_db: str | Path | None = None,
        clock: Clock = time.time,
    ) -> "GatewayProtectedMemoryAuthorizer":
        path = protected_memory_grant_db(replay_db)
        return cls(
            protected_memory_secret(),
            replay_ledger=ProtectedMemoryGrantReplayLedger(path),
            clock=clock,
        )

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
        query = _canonical_text("query", claims["query"], 4_096, allow_empty=True)
        body_sha256 = _canonical_text("body sha256", claims["body_sha256"], 64)
        if _SHA256_RE.fullmatch(body_sha256) is None:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant body digest is invalid"
            )
        if method != method.upper() or method != request.method.upper():
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant method mismatch"
            )
        if path != request.url.path:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant path mismatch"
            )
        if query != request.url.query:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant query mismatch"
            )
        actual_body_sha256 = getattr(
            request.state,
            "agent3_memory_body_sha256",
            None,
        )
        if actual_body_sha256 != body_sha256:
            raise ProtectedMemoryApiAuthorizationError(
                "protected memory grant body mismatch"
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

        if granted_action is ProtectedMemoryApiAction.WRITE_PRIVATE:
            self._replay_ledger.consume(
                nonce=nonce,
                action=granted_action,
                device_id=device_id,
                request_id=request_id,
                now=now,
                expires_at=expires_at,
            )
        else:
            with self._lock:
                expired = [
                    key for key, expiry in self._seen_reads.items() if expiry <= now
                ]
                for key in expired:
                    self._seen_reads.pop(key, None)
                if nonce in self._seen_reads:
                    raise ProtectedMemoryApiAuthorizationError(
                        "protected memory grant has already been consumed"
                    )
                self._seen_reads[nonce] = expires_at

        return ProtectedMemoryApiGrant(
            principal=f"device:{device_id}",
            action=granted_action,
            request_id=request_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
