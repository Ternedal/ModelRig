from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory import DurableCandidateWrite, MemoryCandidate, MemoryCompletedTurnWriteService
from app.memory.write_api import build_memory4_write_router


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


async def empty_extract(_turn) -> tuple[MemoryCandidate, ...]:
    return ()


def forbidden_commit(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    raise AssertionError("invalid requests must not reach commit")


app = FastAPI()
app.include_router(
    build_memory4_write_router(
        MemoryCompletedTurnWriteService(
            extract=empty_extract,
            commit=forbidden_commit,
        )
    )
)
secret = "W04-invalid-private-input-9fd3"
with TestClient(app) as client:
    extra = client.post(
        "/experimental/memory4/completed-turn",
        json={
            "user_text": secret,
            "assistant_text": "Noteret.",
            "source_ref": "conversation:w04-invalid",
            "unexpected": secret,
        },
    )
    wrong_type = client.post(
        "/experimental/memory4/completed-turn",
        json={
            "user_text": 123,
            "assistant_text": secret,
            "source_ref": "conversation:w04-invalid-type",
        },
    )
    malformed = client.post(
        "/experimental/memory4/completed-turn",
        content=("{\"user_text\":\"" + secret).encode(),
        headers={"content-type": "application/json"},
    )

for response in (extra, wrong_type, malformed):
    check(
        response.status_code == 422
        and response.json() == {"detail": "invalid memory write request"}
        and secret not in response.text
        and "source_ref" not in response.text
        and "input" not in response.text,
        "W04 invalid request is a fixed value-free 422",
    )

print(f"\n===== MEMORY 4 W04 VALIDATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
