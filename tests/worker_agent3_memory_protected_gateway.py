#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protected_api import (  # noqa: E402
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
)
from app.agent3.memory_protected_gateway import (  # noqa: E402
    GatewayProtectedMemoryAuthorizer,
    MEMORY_API_SECRET_ENV,
    MEMORY_GRANT_DB_ENV,
    MEMORY_GRANT_HEADER,
    MEMORY_GRANT_SCHEMA,
    MEMORY_STORE_ENV,
    ProtectedMemoryGrantReplayLedger,
    memory_store_mode,
    protected_memory_secret,
)

SECRET = b"t033-protected-memory-gateway-test-secret-0123456789"
DOMAIN = MEMORY_GRANT_SCHEMA.encode("ascii") + b"\x00"
NOW = 10_000.0
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def claims(
    *,
    action: str = "read_metadata",
    request_id: str = "req-gateway-001",
    method: str = "GET",
    path: str = "/experimental/agent3/memory/search",
    query: str = "",
    body_sha256: str = EMPTY_SHA,
    nonce: bytes = b"n" * 32,
    issued_at: float = NOW - 1,
    expires_at: float = NOW + 30,
) -> dict[str, object]:
    return {
        "schema": MEMORY_GRANT_SCHEMA,
        "nonce": b64(nonce),
        "device_id": "paired-device-1",
        "action": action,
        "request_id": request_id,
        "method": method,
        "path": path,
        "query": query,
        "body_sha256": body_sha256,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def token_for(value: dict[str, object], *, secret: bytes = SECRET) -> str:
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    payload_part = b64(payload)
    signature = hmac.new(secret, DOMAIN + payload_part.encode("ascii"), hashlib.sha256).digest()
    return payload_part + "." + b64(signature)


def request_for(
    token: str,
    *,
    request_id: str = "req-gateway-001",
    method: str = "GET",
    path: str = "/experimental/agent3/memory/search",
    query: str = "",
    body_sha256: str = EMPTY_SHA,
) -> Request:
    headers = [
        (b"x-request-id", request_id.encode("ascii")),
        (MEMORY_GRANT_HEADER.lower().encode("ascii"), token.encode("ascii")),
    ]
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query.encode("ascii"),
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8008),
        }
    )
    request.state.agent3_memory_body_sha256 = body_sha256
    return request


def refused(fn, label: str) -> None:
    try:
        fn()
    except ProtectedMemoryApiAuthorizationError:
        check(True, label)
    else:
        check(False, label)


check(memory_store_mode("") == "legacy", "empty store mode selects legacy explicitly")
check(memory_store_mode("legacy") == "legacy", "legacy mode is accepted")
check(memory_store_mode("protected") == "protected", "protected mode is accepted")
refused(lambda: memory_store_mode(" protected"), "non-canonical store mode is refused")
refused(lambda: memory_store_mode("auto"), "unknown store mode is refused")
check(protected_memory_secret(SECRET) == SECRET, "32+ byte gateway secret is accepted")
refused(lambda: protected_memory_secret(b"short"), "short gateway secret is refused")

with tempfile.TemporaryDirectory(prefix="kaliv-t033-gateway-") as raw:
    tmp = Path(raw)

    def authorizer(name: str, *, clock=lambda: NOW):
        return GatewayProtectedMemoryAuthorizer(
            SECRET,
            replay_ledger=ProtectedMemoryGrantReplayLedger(tmp / f"{name}.db"),
            clock=clock,
        )

    fresh = token_for(claims())
    verifier = authorizer("fresh")
    grant = verifier(request_for(fresh), ProtectedMemoryApiAction.READ_METADATA)
    check(
        grant.principal == "device:paired-device-1"
        and grant.action is ProtectedMemoryApiAction.READ_METADATA
        and grant.request_id == "req-gateway-001",
        "fresh exact grant returns a typed device-bound authorization",
    )
    refused(
        lambda: verifier(request_for(fresh), ProtectedMemoryApiAction.READ_METADATA),
        "read grant nonce is process-single-use at the worker boundary",
    )

    cases: list[
        tuple[str, dict[str, object], dict[str, str], ProtectedMemoryApiAction]
    ] = [
        (
            "wrong action",
            claims(action="status", nonce=b"a" * 32),
            {},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "wrong request id",
            claims(nonce=b"b" * 32),
            {"request_id": "different"},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "wrong method",
            claims(nonce=b"c" * 32),
            {"method": "POST"},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "wrong path",
            claims(nonce=b"d" * 32),
            {"path": "/experimental/agent3/memory/other"},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "wrong query",
            claims(query="q=one", nonce=b"q" * 32),
            {"query": "q=two"},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "wrong body",
            claims(body_sha256="1" * 64, nonce=b"r" * 32),
            {"body_sha256": "2" * 64},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "expired",
            claims(nonce=b"e" * 32, issued_at=NOW - 60, expires_at=NOW - 1),
            {},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "future-dated",
            claims(nonce=b"f" * 32, issued_at=NOW + 6, expires_at=NOW + 30),
            {},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
        (
            "overlong lifetime",
            claims(nonce=b"g" * 32, issued_at=NOW - 1, expires_at=NOW + 121),
            {},
            ProtectedMemoryApiAction.READ_METADATA,
        ),
    ]
    for index, (label, payload, request_overrides, expected_action) in enumerate(cases):
        candidate = authorizer(f"case-{index}")
        refused(
            lambda payload=payload, request_overrides=request_overrides, candidate=candidate,
            expected_action=expected_action: candidate(
                request_for(token_for(payload), **request_overrides),
                expected_action,
            ),
            f"{label} grant is refused",
        )

    wrong_secret = token_for(claims(nonce=b"h" * 32), secret=b"z" * 48)
    refused(
        lambda: authorizer("wrong-secret")(
            request_for(wrong_secret), ProtectedMemoryApiAction.READ_METADATA
        ),
        "wrong signature is refused",
    )

    unknown = claims(nonce=b"i" * 32)
    unknown["extra"] = True
    refused(
        lambda: authorizer("unknown")(
            request_for(token_for(unknown)), ProtectedMemoryApiAction.READ_METADATA
        ),
        "unknown payload fields are refused",
    )

    short_nonce = claims(nonce=b"j")
    refused(
        lambda: authorizer("short-nonce")(
            request_for(token_for(short_nonce)), ProtectedMemoryApiAction.READ_METADATA
        ),
        "non-256-bit nonce is refused",
    )

    missing_header_request = request_for(fresh)
    missing_header_request.scope["headers"] = [(b"x-request-id", b"req-gateway-001")]
    refused(
        lambda: authorizer("missing")(
            missing_header_request, ProtectedMemoryApiAction.READ_METADATA
        ),
        "missing internal gateway header is refused",
    )

    write_body_sha = hashlib.sha256(b'{"value":"private"}').hexdigest()
    write_payload = claims(
        action="write_private",
        method="POST",
        path="/experimental/agent3/memory",
        body_sha256=write_body_sha,
        nonce=b"w" * 32,
    )
    write_token = token_for(write_payload)
    write_ledger_path = tmp / "durable-write.db"
    first_writer = GatewayProtectedMemoryAuthorizer(
        SECRET,
        replay_ledger=ProtectedMemoryGrantReplayLedger(write_ledger_path),
        clock=lambda: NOW,
    )
    first_writer(
        request_for(
            write_token,
            method="POST",
            path="/experimental/agent3/memory",
            body_sha256=write_body_sha,
        ),
        ProtectedMemoryApiAction.WRITE_PRIVATE,
    )
    restarted_writer = GatewayProtectedMemoryAuthorizer(
        SECRET,
        replay_ledger=ProtectedMemoryGrantReplayLedger(write_ledger_path),
        clock=lambda: NOW,
    )
    refused(
        lambda: restarted_writer(
            request_for(
                write_token,
                method="POST",
                path="/experimental/agent3/memory",
                body_sha256=write_body_sha,
            ),
            ProtectedMemoryApiAction.WRITE_PRIVATE,
        ),
        "write grant replay is refused after authorizer restart",
    )

    old_store = os.environ.get(MEMORY_STORE_ENV)
    old_secret = os.environ.get(MEMORY_API_SECRET_ENV)
    old_db = os.environ.get(MEMORY_GRANT_DB_ENV)
    try:
        os.environ[MEMORY_STORE_ENV] = "protected"
        os.environ[MEMORY_API_SECRET_ENV] = SECRET.decode("ascii")
        os.environ[MEMORY_GRANT_DB_ENV] = str(tmp / "environment.db")
        env_authorizer = GatewayProtectedMemoryAuthorizer.from_environment(
            clock=lambda: NOW
        )
        env_token = token_for(claims(nonce=b"k" * 32))
        env_grant = env_authorizer(
            request_for(env_token), ProtectedMemoryApiAction.READ_METADATA
        )
        check(
            env_grant.principal.endswith("paired-device-1"),
            "environment factory uses the exact shared secret and ledger",
        )
    finally:
        for name, value in (
            (MEMORY_STORE_ENV, old_store),
            (MEMORY_API_SECRET_ENV, old_secret),
            (MEMORY_GRANT_DB_ENV, old_db),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

print(f"\n===== AGENT3 PROTECTED MEMORY GATEWAY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
