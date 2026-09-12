from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory.context_api import (
    MAX_MEMORY4_CONTEXT_BODY_BYTES,
    build_memory4_context_router,
)
from app.memory.context_service import MemoryContextForTurnService


passed = failed = 0
ROUTE = "/experimental/memory4/context-for-turn"
INVALID_DETAIL = "invalid memory context request"


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class MustNotRunService(MemoryContextForTurnService):
    def __init__(self) -> None:
        # These regressions terminate at admission/body validation and must never
        # reach retrieval. Avoid opening any memory substrate in the focused suite.
        pass

    async def context_for_turn(self, _request):
        raise AssertionError("R04-H1 validation/privacy regression reached retrieval")


service = MustNotRunService()


def http_scope(*, client_host: str, headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ROUTE,
        "raw_path": ROUTE.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [(b"content-type", b"application/json")],
        "client": (client_host, 4242),
        "server": ("testserver", 80),
        "state": {},
    }


async def invoke_asgi(app: FastAPI, scope: dict, receive):
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


def response_status(messages: list[dict]) -> int | None:
    for message in messages:
        if message.get("type") == "http.response.start":
            return int(message["status"])
    return None


def response_json(messages: list[dict]) -> dict:
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message.get("type") == "http.response.body"
    )
    return json.loads(body.decode("utf-8"))


# Admission must happen before the ASGI receive channel is touched at all.
blocked_app = FastAPI()
blocked_app.include_router(
    build_memory4_context_router(service, loopback_allowed=lambda _request: False)
)
receive_state = {"called": False}


async def must_not_receive():
    receive_state["called"] = True
    raise AssertionError("non-loopback R04 request body must not be consumed")


blocked_messages = asyncio.run(
    invoke_asgi(
        blocked_app,
        http_scope(
            client_host="203.0.113.92",
            headers=[
                (b"content-type", b"application/json"),
                (b"content-length", b"999999999"),
            ],
        ),
        must_not_receive,
    )
)
check(
    response_status(blocked_messages) == 403 and not receive_state["called"],
    "R04-H1 denies non-loopback before consuming request body",
)

# Automatic FastAPI/Pydantic 422 responses can reflect rejected private input.
# The route now owns validation and always emits one value-free detail.
private_marker = "R04-H1-PRIVATE-QUERY-MARKER-93c1"
validation_app = FastAPI()
validation_app.include_router(
    build_memory4_context_router(service, loopback_allowed=lambda _request: True)
)
client = TestClient(validation_app)
invalid = client.post(
    ROUTE,
    json={
        "query": private_marker,
        "subjects": ["private-subject"],
        "unexpected_private_field": "private-extra-value",
    },
)
check(
    invalid.status_code == 422
    and invalid.json() == {"detail": INVALID_DETAIL}
    and private_marker not in invalid.text
    and "private-subject" not in invalid.text
    and "private-extra-value" not in invalid.text,
    "R04-H1 returns one value-free 422 for strict-body validation failures",
)

malformed = client.post(
    ROUTE,
    content=b'{"query":"R04-H1-MALFORMED-PRIVATE-MARKER"',
    headers={"content-type": "application/json"},
)
check(
    malformed.status_code == 422
    and malformed.json() == {"detail": INVALID_DETAIL}
    and "R04-H1-MALFORMED-PRIVATE-MARKER" not in malformed.text,
    "R04-H1 redacts malformed JSON validation failures",
)

# A missing/lying Content-Length cannot bypass the route-owned byte cap.
oversized_app = FastAPI()
oversized_app.include_router(
    build_memory4_context_router(service, loopback_allowed=lambda _request: True)
)
oversized_chunk = b"x" * (MAX_MEMORY4_CONTEXT_BODY_BYTES + 1)
oversized_state = {"sent": False}


async def oversized_receive():
    if not oversized_state["sent"]:
        oversized_state["sent"] = True
        return {
            "type": "http.request",
            "body": oversized_chunk,
            "more_body": False,
        }
    return {"type": "http.disconnect"}


oversized_messages = asyncio.run(
    invoke_asgi(
        oversized_app,
        http_scope(client_host="127.0.0.1"),
        oversized_receive,
    )
)
check(
    response_status(oversized_messages) == 422
    and response_json(oversized_messages) == {"detail": INVALID_DETAIL},
    "R04-H1 enforces bounded body bytes before JSON/Pydantic parsing",
)

client.close()
print(
    f"\n===== MEMORY 4 R04-H1 VALIDATION PRIVACY: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
