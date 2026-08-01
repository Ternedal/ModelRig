#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protected_api import (  # noqa: E402
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
    ProtectedMemoryApiGrant,
    build_protected_memory_router,
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


class FakeStatus:
    def to_dict(self) -> dict[str, object]:
        return {"query_only": True, "production_activation": False}


class FakeReader:
    def __init__(self) -> None:
        self.status = FakeStatus()
        self.list_calls: list[dict[str, object]] = []
        self.search_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls = 0

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return []

    def search_metadata(self, query: str, **kwargs):
        self.search_calls.append((query, kwargs))
        return []

    def get(self, *args, **kwargs):
        self.get_calls += 1
        raise AssertionError("invalid query reached protected reader")


class FakeWriter:
    def delete(self, *args, **kwargs):
        raise AssertionError("invalid query reached protected writer")


reader = FakeReader()
writer = FakeWriter()
mode = {"value": "deny"}
authorizer_calls: list[tuple[str, ProtectedMemoryApiAction]] = []
now = 10_000.0


def authorizer(request, action):
    request_id = request.headers.get("X-Request-ID", "")
    authorizer_calls.append((request_id, action))
    if mode["value"] == "deny":
        raise ProtectedMemoryApiAuthorizationError("denied by fixture")
    return ProtectedMemoryApiGrant(
        principal="device:query-order",
        action=action,
        request_id=request_id,
        issued_at=now - 1,
        expires_at=now + 30,
    )


app = FastAPI()
app.include_router(
    build_protected_memory_router(
        reader,  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
        authorizer=authorizer,
        clock=lambda: now,
    )
)
client = TestClient(app)
headers = {"X-Request-ID": "query-order-001"}
marker = "T033-QUERY-VALIDATION-MARKER-7d91"

# Invalid or missing query values must not pre-empt authorization.
for method, path, action, label in (
    ("get", f"/experimental/agent3/memory?limit={marker}", ProtectedMemoryApiAction.READ_METADATA, "list limit"),
    ("get", f"/experimental/agent3/memory?include_expired={marker}", ProtectedMemoryApiAction.READ_METADATA, "list boolean"),
    ("get", "/experimental/agent3/memory/search", ProtectedMemoryApiAction.READ_METADATA, "missing search query"),
    ("get", f"/experimental/agent3/memory/search?q=ok&limit={marker}", ProtectedMemoryApiAction.READ_METADATA, "search limit"),
    ("delete", f"/experimental/agent3/memory/memory-1?expected_updated_at={marker}", ProtectedMemoryApiAction.WRITE_PRIVATE, "delete timestamp"),
):
    before = len(authorizer_calls)
    response = getattr(client, method)(path, headers=headers)
    check(
        response.status_code == 403
        and response.json() == {"detail": "protected memory authorization denied"}
        and marker not in response.text,
        f"authorization precedes declarative validation for {label}",
    )
    check(
        len(authorizer_calls) == before + 1
        and authorizer_calls[-1][1] is action,
        f"authorizer receives the typed action before rejecting {label}",
    )

mode["value"] = "allow"

# After authorization, invalid query data is mapped to the fixed bounded 422.
for method, path, label in (
    ("get", f"/experimental/agent3/memory?limit={marker}", "invalid list limit"),
    ("get", "/experimental/agent3/memory?limit=0", "out-of-range list limit"),
    ("get", f"/experimental/agent3/memory?include_expired={marker}", "invalid list boolean"),
    ("get", "/experimental/agent3/memory?limit=1&limit=2", "repeated list limit"),
    ("get", "/experimental/agent3/memory/search", "missing search query"),
    ("get", f"/experimental/agent3/memory/search?q=ok&limit={marker}", "invalid search limit"),
    ("delete", "/experimental/agent3/memory/memory-1", "missing delete timestamp"),
    ("delete", "/experimental/agent3/memory/memory-1?expected_updated_at=NaN", "non-finite delete timestamp"),
    ("delete", "/experimental/agent3/memory/memory-1?expected_updated_at=Infinity", "infinite delete timestamp"),
    ("delete", f"/experimental/agent3/memory/memory-1?expected_updated_at={marker}", "invalid delete timestamp"),
):
    response = getattr(client, method)(path, headers=headers)
    check(
        response.status_code == 422
        and response.json() == {"detail": "protected memory request rejected"}
        and marker not in response.text,
        f"{label} uses the fixed query-validation error body",
    )

check(
    reader.get_calls == 0,
    "invalid delete query values are rejected before protected-store reads",
)

valid_list = client.get(
    "/experimental/agent3/memory?subject=Anders&include_expired=yes&limit=7",
    headers=headers,
)
check(valid_list.status_code == 200 and valid_list.json() == {"memories": []}, "valid list query still succeeds")
check(
    reader.list_calls[-1]["subject"] == "Anders"
    and reader.list_calls[-1]["include_expired"] is True
    and reader.list_calls[-1]["limit"] == 7,
    "valid list query is parsed after authorization with the original bounds",
)

valid_search = client.get(
    "/experimental/agent3/memory/search?q=project&limit=8",
    headers=headers,
)
check(valid_search.status_code == 200 and valid_search.json() == {"memories": []}, "valid search query still succeeds")
check(
    reader.search_calls[-1][0] == "project"
    and reader.search_calls[-1][1]["limit"] == 8,
    "valid search query is parsed after authorization",
)

print(
    f"\n===== AGENT3 PROTECTED MEMORY QUERY AUTH ORDER: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
