from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.memory import MemoryStore
from app.agent3.memory_protected_lookup import ProtectedMemoryVerbatimLookupMigrator
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import (
    CompletedMemoryTurn,
    DurableCandidateWrite,
    MemoryCandidate,
    MemoryCompletedTurnWriteService,
    MemoryExtractionError,
)
from app.memory.write_api import build_memory4_write_router
from app.memory.write_mount import (
    MEMORY4_WRITE_FLAG,
    MEMORY4_WRITE_INDEXED_PROTECTED_FLAG,
    close_memory4_write,
    mount_memory4_write,
)


class TestAeadProvider:
    provider_id = "test-memory4-w04a-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"memory4-w04a-test-provider-key-v1"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        block = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(output[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.calls += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("W04-A test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("W04-A test ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


class MustNotBeConstructed:
    def __init__(self) -> None:
        raise AssertionError("flag-off W04-A must not construct a provider")


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


@contextmanager
def environment(**values: str | None):
    previous = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def confirmed(turn: CompletedMemoryTurn) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=turn.user_text.strip(),
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=turn.source_ref.strip(),
        confidence=1.0,
        review_status="confirmed",
        evidence=turn.user_text.strip(),
    )


async def one_confirmed(turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return (confirmed(turn),)


async def no_candidates(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return ()


# Router contract: loopback-only, strict body and value-free response.
commit_calls = 0


def forbidden_commit(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    global commit_calls
    commit_calls += 1
    raise AssertionError("empty extraction must not commit")


router_service = MemoryCompletedTurnWriteService(
    extract=no_candidates,
    commit=forbidden_commit,
)
router_app = FastAPI()
router_app.include_router(build_memory4_write_router(router_service))
router_client = TestClient(router_app)
payload = {
    "user_text": "W04-A empty request",
    "assistant_text": "Okay",
    "source_ref": "conversation:w04a-api-empty",
}
response = router_client.post(
    "/experimental/memory4/commit-completed-turn",
    json=payload,
)
body = response.json()
check(
    response.status_code == 200
    and body["candidate_count"] == 0
    and body["created_ids"] == []
    and body["sent_to_store"] is False
    and commit_calls == 0,
    "W04-A loopback route returns W03 zero receipt without storage",
)
strict = router_client.post(
    "/experimental/memory4/commit-completed-turn",
    json={**payload, "unexpected": "forbidden"},
)
check(strict.status_code == 422, "W04-A request rejects unknown fields")
wrong_type = router_client.post(
    "/experimental/memory4/commit-completed-turn",
    json={**payload, "user_text": 123},
)
check(wrong_type.status_code == 422, "W04-A request rejects coerced text types")

blocked_app = FastAPI()
blocked_app.include_router(
    build_memory4_write_router(router_service, loopback_allowed=lambda _request: False)
)
blocked = TestClient(blocked_app).post(
    "/experimental/memory4/commit-completed-turn",
    json=payload,
)
check(blocked.status_code == 403, "W04-A route fails closed for non-loopback policy")

secret_marker = "W04A-PRIVATE-FAILURE-MARKER-91af"


async def failing_extract(_turn: CompletedMemoryTurn):
    raise MemoryExtractionError(secret_marker)


failure_service = MemoryCompletedTurnWriteService(
    extract=failing_extract,
    commit=forbidden_commit,
)
failure_app = FastAPI()
failure_app.include_router(build_memory4_write_router(failure_service))
failure = TestClient(failure_app).post(
    "/experimental/memory4/commit-completed-turn",
    json=payload,
)
check(
    failure.status_code == 503
    and secret_marker not in failure.text
    and failure.json().get("detail") == "memory completed-turn write unavailable",
    "W04-A sanitizes extraction/write failures",
)

# Flag-off mount is inert before DB/provider/extractor construction.
flag_off_app = FastAPI()
flag_off_routes = len(flag_off_app.router.routes)
with environment(
    **{
        MEMORY4_WRITE_FLAG: None,
        "KALIV_AGENT3_MEMORY_DB": str(
            Path(tempfile.mkdtemp(prefix="memory4-w04a-off-")) / "memory.db"
        ),
    }
):
    mounted = mount_memory4_write(
        flag_off_app,
        extract_candidates=lambda _turn: (_ for _ in ()).throw(
            AssertionError("flag-off extractor must remain inert")
        ),
        protected_provider_factory=MustNotBeConstructed,
    )
check(
    mounted is False
    and len(flag_off_app.router.routes) == flag_off_routes
    and not getattr(flag_off_app.state, "memory4_write_mounted", False),
    "W04-A flag-off mount opens nothing and registers no route",
)

# Legacy mount exercises the real W03 legacy adapter through HTTP.
legacy_path = Path(tempfile.mkdtemp(prefix="memory4-w04a-legacy-")) / "memory.db"
legacy_app = FastAPI()
with environment(
    **{
        MEMORY4_WRITE_FLAG: "1",
        MEMORY4_WRITE_INDEXED_PROTECTED_FLAG: None,
        "KALIV_AGENT3_MEMORY_STORE": "legacy",
        "KALIV_AGENT3_MEMORY_DB": str(legacy_path),
    }
):
    check(
        mount_memory4_write(
            legacy_app,
            extract_candidates=one_confirmed,
            loopback_allowed=lambda _request: True,
        ),
        "W04-A legacy mount succeeds after explicit opt-in",
    )
    legacy_client = TestClient(legacy_app)
    legacy_payload = {
        "user_text": "W04-A legacy durable statement 51d4",
        "assistant_text": "Okay",
        "source_ref": "conversation:w04a-legacy",
    }
    first = legacy_client.post(
        "/experimental/memory4/commit-completed-turn",
        json=legacy_payload,
    )
    second = legacy_client.post(
        "/experimental/memory4/commit-completed-turn",
        json=legacy_payload,
    )
    check(
        first.status_code == 200
        and len(first.json()["created_ids"]) == 1
        and second.status_code == 200
        and second.json()["deduped_ids"] == first.json()["created_ids"],
        "W04-A legacy route creates then exact-dedupes through W03",
    )
    serialized = str(first.json())
    check(
        legacy_payload["user_text"] not in serialized
        and legacy_payload["source_ref"] not in serialized,
        "W04-A legacy response exposes no candidate value/source_ref",
    )
    close_memory4_write(legacy_app)
    close_memory4_write(legacy_app)
    check(
        getattr(legacy_app.state, "memory4_write_substrate", None) is None
        and not getattr(legacy_app.state, "memory4_write_mounted", False),
        "W04-A cleanup is deterministic and idempotent",
    )

# Protected mount uses existing migration + local-management writer authority.
protected_path = Path(tempfile.mkdtemp(prefix="memory4-w04a-protected-")) / "memory.db"
bootstrap = MemoryStore(str(protected_path))
bootstrap.close()
codec = MemoryProtectionCodec(TestAeadProvider())
check(
    MemoryProtectionMigrator(protected_path, codec).migrate().complete,
    "W04-A protected fixture migration completes",
)
protected_app = FastAPI()
with environment(
    **{
        MEMORY4_WRITE_FLAG: "1",
        MEMORY4_WRITE_INDEXED_PROTECTED_FLAG: None,
        "KALIV_AGENT3_MEMORY_STORE": "protected",
        "KALIV_AGENT3_MEMORY_DB": str(protected_path),
    }
):
    check(
        mount_memory4_write(
            protected_app,
            extract_candidates=one_confirmed,
            protected_provider_factory=TestAeadProvider,
            loopback_allowed=lambda _request: True,
        ),
        "W04-A protected mount succeeds after explicit migration",
    )
    protected_payload = {
        "user_text": "W04-A protected durable statement 82ce",
        "assistant_text": "Okay",
        "source_ref": "conversation:w04a-protected",
    }
    protected_response = TestClient(protected_app).post(
        "/experimental/memory4/commit-completed-turn",
        json=protected_payload,
    )
    protected_id = protected_response.json()["created_ids"][0]
    conn = sqlite3.connect(protected_path)
    try:
        protected_row = conn.execute(
            "SELECT value,source_ref,protection_state FROM agent_memories WHERE id=?",
            (protected_id,),
        ).fetchone()
    finally:
        conn.close()
    check(
        protected_response.status_code == 200
        and protected_row is not None
        and protected_row[0] == ""
        and protected_row[1] is None
        and protected_row[2] == "protected",
        "W04-A protected route keeps private fields out of plaintext columns",
    )
    close_memory4_write(protected_app)

# Indexed protected mode is a separate explicit opt-in and never auto-migrates.
check(
    ProtectedMemoryVerbatimLookupMigrator(protected_path, codec).migrate().complete,
    "W04-A indexed fixture sidecar migration completes explicitly",
)
indexed_app = FastAPI()
with environment(
    **{
        MEMORY4_WRITE_FLAG: "1",
        MEMORY4_WRITE_INDEXED_PROTECTED_FLAG: "1",
        "KALIV_AGENT3_MEMORY_STORE": "protected",
        "KALIV_AGENT3_MEMORY_DB": str(protected_path),
    }
):
    check(
        mount_memory4_write(
            indexed_app,
            extract_candidates=one_confirmed,
            protected_provider_factory=TestAeadProvider,
            loopback_allowed=lambda _request: True,
        ),
        "W04-A indexed protected mount requires explicit opt-in",
    )
    indexed_payload = {
        "user_text": "W04-A indexed durable statement c2a9",
        "assistant_text": "Okay",
        "source_ref": "conversation:w04a-indexed",
    }
    indexed_response = TestClient(indexed_app).post(
        "/experimental/memory4/commit-completed-turn",
        json=indexed_payload,
    )
    indexed_id = indexed_response.json()["created_ids"][0]
    conn = sqlite3.connect(protected_path)
    try:
        sidecar = conn.execute(
            "SELECT value_hmac FROM agent_memory_protected_verbatim_lookup "
            "WHERE memory_id=?",
            (indexed_id,),
        ).fetchone()
    finally:
        conn.close()
    check(
        indexed_response.status_code == 200
        and sidecar is not None
        and len(str(sidecar[0])) == 64
        and str(sidecar[0])
        != hashlib.sha256(indexed_payload["user_text"].encode()).hexdigest(),
        "W04-A indexed protected write maintains keyed blind selector",
    )
    close_memory4_write(indexed_app)

# An indexed flag in legacy mode is rejected before route publication.
invalid_app = FastAPI()
invalid_routes = len(invalid_app.router.routes)
invalid_path = Path(tempfile.mkdtemp(prefix="memory4-w04a-invalid-")) / "memory.db"
refused = False
with environment(
    **{
        MEMORY4_WRITE_FLAG: "1",
        MEMORY4_WRITE_INDEXED_PROTECTED_FLAG: "1",
        "KALIV_AGENT3_MEMORY_STORE": "legacy",
        "KALIV_AGENT3_MEMORY_DB": str(invalid_path),
    }
):
    try:
        mount_memory4_write(
            invalid_app,
            extract_candidates=one_confirmed,
            loopback_allowed=lambda _request: True,
        )
    except RuntimeError:
        refused = True
check(
    refused
    and len(invalid_app.router.routes) == invalid_routes
    and not getattr(invalid_app.state, "memory4_write_mounted", False),
    "W04-A invalid storage/index mode rolls back without route publication",
)

print(f"\n===== MEMORY 4 W04-A WRITE SURFACE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
