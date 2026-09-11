from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory import MemoryCompletedTurnWriteService
from app.memory.write_api import (
    INVALID_COMPLETED_TURN_WRITE_DETAIL,
    MAX_COMPLETED_TURN_WRITE_BODY_BYTES,
    build_memory4_write_router,
)


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


extract_calls = 0
commit_calls = 0


async def no_candidates(_turn):
    global extract_calls
    extract_calls += 1
    return ()


def forbidden_commit(_candidates):
    global commit_calls
    commit_calls += 1
    raise AssertionError("zero-candidate admission test must not reach storage")


service = MemoryCompletedTurnWriteService(
    extract=no_candidates,
    commit=forbidden_commit,
)


def test_client(*, allowed=True):
    app = FastAPI()
    app.include_router(
        build_memory4_write_router(
            service,
            loopback_allowed=lambda _request: allowed,
        )
    )
    return TestClient(app)


valid_payload = {
    "user_text": "W04-H1 valid user text",
    "assistant_text": "Okay",
    "source_ref": "conversation:w04-h1-valid",
}
valid = test_client().post(
    "/experimental/memory4/commit-completed-turn",
    json=valid_payload,
)
check(
    valid.status_code == 200
    and valid.json().get("candidate_count") == 0
    and valid.json().get("sent_to_store") is False,
    "W04-H1 preserves the valid W04-A zero-candidate contract",
)

private_marker = "W04H1-PRIVATE-VALIDATION-MARKER-51c8"
unknown = test_client().post(
    "/experimental/memory4/commit-completed-turn",
    json={**valid_payload, "unexpected": private_marker},
)
check(
    unknown.status_code == 422
    and unknown.json() == {"detail": INVALID_COMPLETED_TURN_WRITE_DETAIL}
    and private_marker not in unknown.text,
    "W04-H1 redacts unknown-field validation input from 422",
)

wrong_type = test_client().post(
    "/experimental/memory4/commit-completed-turn",
    json={**valid_payload, "user_text": 123},
)
check(
    wrong_type.status_code == 422
    and wrong_type.json() == {"detail": INVALID_COMPLETED_TURN_WRITE_DETAIL}
    and "123" not in wrong_type.text,
    "W04-H1 redacts strict-type validation input from 422",
)

malformed_marker = "W04H1-MALFORMED-PRIVATE-7bd2"
malformed = test_client().post(
    "/experimental/memory4/commit-completed-turn",
    content=(
        '{"user_text":"'
        + malformed_marker
        + '","assistant_text":"unterminated"'
    ),
    headers={"content-type": "application/json"},
)
check(
    malformed.status_code == 422
    and malformed.json() == {"detail": INVALID_COMPLETED_TURN_WRITE_DETAIL}
    and malformed_marker not in malformed.text,
    "W04-H1 redacts malformed JSON input from 422",
)

before_oversize_extract = extract_calls
oversized = test_client().post(
    "/experimental/memory4/commit-completed-turn",
    content=b"x" * (MAX_COMPLETED_TURN_WRITE_BODY_BYTES + 1),
    headers={"content-type": "application/json"},
)
check(
    oversized.status_code == 422
    and oversized.json() == {"detail": INVALID_COMPLETED_TURN_WRITE_DETAIL}
    and extract_calls == before_oversize_extract,
    "W04-H1 rejects declared oversized body before extraction/parsing",
)


async def invoke_asgi_without_body_read(*, allowed: bool):
    app = FastAPI()
    app.include_router(
        build_memory4_write_router(
            service,
            loopback_allowed=lambda _request: allowed,
        )
    )
    reads = 0
    sent = []

    async def receive():
        nonlocal reads
        reads += 1
        raise AssertionError("denied W04-A request consumed private body")

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/experimental/memory4/commit-completed-turn",
        "raw_path": b"/experimental/memory4/commit-completed-turn",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", b"4096"),
        ],
        "client": ("203.0.113.71", 43110),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    status = next(
        message["status"]
        for message in sent
        if message.get("type") == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message.get("type") == "http.response.body"
    )
    return reads, status, body


reads, status, denied_body = asyncio.run(invoke_asgi_without_body_read(allowed=False))
check(
    reads == 0
    and status == 403
    and b"loopback-only" in denied_body,
    "W04-H1 denies non-loopback request before any body receive",
)


async def invoke_streamed_oversize():
    app = FastAPI()
    app.include_router(
        build_memory4_write_router(
            service,
            loopback_allowed=lambda _request: True,
        )
    )
    sent = []
    chunks = [
        b"x" * (MAX_COMPLETED_TURN_WRITE_BODY_BYTES // 2),
        b"y" * (MAX_COMPLETED_TURN_WRITE_BODY_BYTES // 2 + 1),
    ]

    async def receive():
        if chunks:
            chunk = chunks.pop(0)
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": bool(chunks),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/experimental/memory4/commit-completed-turn",
        "raw_path": b"/experimental/memory4/commit-completed-turn",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 43111),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    status = next(
        message["status"]
        for message in sent
        if message.get("type") == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message.get("type") == "http.response.body"
    )
    return status, json.loads(body)


before_streamed_extract = extract_calls
stream_status, stream_body = asyncio.run(invoke_streamed_oversize())
check(
    stream_status == 422
    and stream_body == {"detail": INVALID_COMPLETED_TURN_WRITE_DETAIL}
    and extract_calls == before_streamed_extract,
    "W04-H1 enforces byte cap while streaming when Content-Length is absent",
)

check(commit_calls == 0, "W04-H1 admission qualification never reaches storage")

print(
    f"\n===== MEMORY 4 W04-H1 WRITE ADMISSION: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
