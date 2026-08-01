#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protected_api import (  # noqa: E402
    ProtectedMemoryApiAction,
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


@dataclass
class FakeRecord:
    id: str
    subject: str = "Anders"
    predicate: str = "strict_model"
    kind: str = "fact"
    sensitivity: str = "private"
    confidence: float = 1.0
    lifecycle_status: str = "active"
    review_status: str = "confirmed"
    source_type: str = "user_explicit"
    source_ref: str | None = None
    created_at: float = 20_000.0
    updated_at: float = 20_000.0
    expires_at: float | None = None
    supersedes_id: str | None = None

    def to_dict(self, *, include_value: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "value": "fixture" if include_value else "",
            "kind": self.kind,
            "sensitivity": self.sensitivity,
            "confidence": self.confidence,
            "lifecycle_status": self.lifecycle_status,
            "review_status": self.review_status,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "supersedes_id": self.supersedes_id,
        }
        return payload


class FakeStatus:
    def to_dict(self) -> dict[str, object]:
        return {"query_only": True, "production_activation": False}


class FakeReader:
    def __init__(self) -> None:
        self.status = FakeStatus()
        self.get_calls = 0

    def get(self, memory_id: str, **kwargs) -> FakeRecord:
        self.get_calls += 1
        return FakeRecord(id=memory_id)


class FakeWriter:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.correct_calls: list[tuple[str, dict[str, object]]] = []

    def create(self, **kwargs) -> FakeRecord:
        self.create_calls.append(kwargs)
        return FakeRecord(
            id="strict-create-001",
            subject=str(kwargs["subject"]),
            predicate=str(kwargs["predicate"]),
            kind=str(kwargs["kind"]),
            confidence=float(kwargs["confidence"]),
            expires_at=kwargs["expires_at"],  # type: ignore[arg-type]
        )

    def correct(self, memory_id: str, **kwargs) -> FakeRecord:
        self.correct_calls.append((memory_id, kwargs))
        return FakeRecord(
            id="strict-correct-002",
            confidence=float(kwargs["confidence"]),
            expires_at=kwargs["expires_at"],  # type: ignore[arg-type]
            supersedes_id=memory_id,
        )


reader = FakeReader()
writer = FakeWriter()
now = 10_000.0
authorizer_actions: list[ProtectedMemoryApiAction] = []


def authorizer(request, action):
    request_id = request.headers.get("X-Request-ID", "")
    authorizer_actions.append(action)
    return ProtectedMemoryApiGrant(
        principal="device:strict-model",
        action=action,
        request_id=request_id,
        method=request.method.upper(),
        path=request.url.path,
        query=request.url.query,
        body_sha256=request.state.agent3_memory_body_sha256,
        issued_at=now - 1,
        expires_at=now + 30,
    )


app = FastAPI()


@app.middleware("http")
async def bind_request_body(request, call_next):
    body = await request.body()
    request.state.agent3_memory_body_sha256 = hashlib.sha256(body).hexdigest()
    return await call_next(request)


app.include_router(
    build_protected_memory_router(
        reader,  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
        authorizer=authorizer,
        clock=lambda: now,
    )
)
client = TestClient(app)
headers = {"X-Request-ID": "strict-model-001"}
marker = "T033-STRICT-MODEL-MARKER-3f81"


def fixed_rejection(response, label: str) -> None:
    check(
        response.status_code == 422
        and response.json() == {"detail": "protected memory request rejected"}
        and marker not in response.text,
        label,
    )


base_create = {
    "subject": "Anders",
    "predicate": "strict_create",
    "value": "private value",
    "kind": "fact",
    "sensitivity": "private",
    "confidence": 0.75,
    "expires_at": 30_000.0,
}

for body, label in (
    ({**base_create, "unexpected": marker}, "create rejects unknown fields"),
    ({**base_create, "confidence": "0.75"}, "create rejects string-to-float coercion"),
    ({**base_create, "confidence": True}, "create rejects boolean-to-float coercion"),
    ({**base_create, "subject": 123}, "create rejects number-to-string coercion"),
    ({**base_create, "expires_at": "30000"}, "create rejects string expiration coercion"),
):
    before = len(writer.create_calls)
    response = client.post(
        "/experimental/agent3/memory",
        headers=headers,
        json=body,
    )
    fixed_rejection(response, label)
    check(
        len(writer.create_calls) == before,
        f"{label} before protected writer create",
    )

base_correct = {
    "expected_updated_at": 20_000.0,
    "value": "corrected private value",
    "confidence": 0.5,
    "expires_at": 40_000.0,
}

for body, label in (
    ({**base_correct, "unexpected": marker}, "correct rejects unknown fields"),
    ({**base_correct, "expected_updated_at": "20000"}, "correct rejects string CAS coercion"),
    ({**base_correct, "confidence": "0.5"}, "correct rejects string confidence coercion"),
    ({**base_correct, "confidence": False}, "correct rejects boolean confidence coercion"),
    ({**base_correct, "expires_at": "40000"}, "correct rejects string expiration coercion"),
):
    before_get = reader.get_calls
    before_correct = len(writer.correct_calls)
    response = client.post(
        "/experimental/agent3/memory/memory-1/correct",
        headers=headers,
        json=body,
    )
    fixed_rejection(response, label)
    check(
        reader.get_calls == before_get
        and len(writer.correct_calls) == before_correct,
        f"{label} before protected reader or writer",
    )

valid_create = client.post(
    "/experimental/agent3/memory",
    headers=headers,
    json=base_create,
)
check(valid_create.status_code == 200, "strict create still accepts canonical JSON types")
check(
    writer.create_calls[-1]["confidence"] == 0.75
    and writer.create_calls[-1]["expires_at"] == 30_000.0,
    "strict create preserves canonical numeric values",
)

valid_correct = client.post(
    "/experimental/agent3/memory/memory-1/correct",
    headers=headers,
    json=base_correct,
)
check(valid_correct.status_code == 200, "strict correction still accepts canonical JSON types")
check(
    writer.correct_calls[-1][1]["expected_updated_at"] == 20_000.0
    and writer.correct_calls[-1][1]["confidence"] == 0.5
    and writer.correct_calls[-1][1]["expires_at"] == 40_000.0,
    "strict correction preserves canonical numeric values",
)
check(
    bool(authorizer_actions)
    and all(
        action is ProtectedMemoryApiAction.WRITE_PRIVATE
        for action in authorizer_actions
    ),
    "strict-model requests retain the typed write-private authorization action",
)

print(
    f"\n===== AGENT3 PROTECTED MEMORY STRICT WRITE MODELS: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
