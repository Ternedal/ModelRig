#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protected_gateway import (  # noqa: E402
    MEMORY_REQUEST_BODY_MAX_BYTES,
    MEMORY_STORE_ATTESTATION_HEADER,
    MEMORY_STORE_ATTESTATION_VALUE,
)
from app.agent3.memory_surface import (  # noqa: E402
    _install_protected_request_boundary,
)


passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


app = FastAPI()
downstream_calls = 0


@app.post("/experimental/agent3/memory")
async def echo_bounded_body(request: Request) -> dict[str, object]:
    global downstream_calls
    downstream_calls += 1
    body = await request.body()
    return {
        "size": len(body),
        "sha256": request.state.agent3_memory_body_sha256,
    }


_install_protected_request_boundary(app)


def run_request(
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict[str, str], bytes, int]:
    sent: list[dict[str, Any]] = []
    receive_calls = 0
    index = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls, index
        receive_calls += 1
        if index >= len(chunks):
            return {"type": "http.disconnect"}
        body = chunks[index]
        index += 1
        return {
            "type": "http.request",
            "body": body,
            "more_body": index < len(chunks),
        }

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/experimental/agent3/memory",
        "raw_path": b"/experimental/agent3/memory",
        "query_string": b"",
        "headers": headers or [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    return int(start["status"]), response_headers, body, receive_calls


before = downstream_calls
status, response_headers, body, receive_calls = run_request(
    [b"must-not-be-read"],
    headers=[
        (b"content-type", b"application/json"),
        (
            b"content-length",
            str(MEMORY_REQUEST_BODY_MAX_BYTES + 1).encode("ascii"),
        ),
    ],
)
check(status == 413, "oversized declared length is refused")
check(receive_calls == 0, "oversized declared length is refused before receive")
check(downstream_calls == before, "declared oversize never reaches downstream")
check(
    json.loads(body) == {"detail": "protected memory request body is too large"}
    and response_headers.get(MEMORY_STORE_ATTESTATION_HEADER.lower())
    == MEMORY_STORE_ATTESTATION_VALUE,
    "declared oversize returns the fixed attested 413 response",
)

first = b"a" * (MEMORY_REQUEST_BODY_MAX_BYTES // 2)
second = b"b" * (MEMORY_REQUEST_BODY_MAX_BYTES // 2 + 1)
third = b"must-remain-unread"
before = downstream_calls
status, response_headers, body, receive_calls = run_request([first, second, third])
check(status == 413, "chunked oversize is refused")
check(receive_calls == 2, "chunked oversize stops at the first crossing chunk")
check(downstream_calls == before, "chunked oversize never reaches downstream")
check(
    json.loads(body) == {"detail": "protected memory request body is too large"}
    and response_headers.get(MEMORY_STORE_ATTESTATION_HEADER.lower())
    == MEMORY_STORE_ATTESTATION_VALUE,
    "chunked oversize returns the fixed attested 413 response",
)

left = b"x" * (MEMORY_REQUEST_BODY_MAX_BYTES // 2)
right = b"y" * (MEMORY_REQUEST_BODY_MAX_BYTES // 2)
expected = left + right
before = downstream_calls
status, response_headers, body, receive_calls = run_request([left, right])
payload = json.loads(body)
check(status == 200, "exact-cap chunked body remains accepted")
check(receive_calls == 2, "exact-cap body consumes only its declared chunks")
check(downstream_calls == before + 1, "accepted body reaches downstream exactly once")
check(
    payload == {
        "size": len(expected),
        "sha256": hashlib.sha256(expected).hexdigest(),
    },
    "bounded body is replayed intact with its streaming digest",
)
check(
    response_headers.get(MEMORY_STORE_ATTESTATION_HEADER.lower())
    == MEMORY_STORE_ATTESTATION_VALUE,
    "accepted bounded response retains protected-store attestation",
)

print(
    f"\n===== AGENT3 PROTECTED MEMORY BODY STREAM: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
