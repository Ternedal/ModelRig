from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.memory import MemoryStore
from app.agent3.memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import MemoryCandidate
from app.memory.context_mount import compose_memory4_context_lifespan
from app.memory.write_mount import close_memory4_write, mount_memory4_write


class TestAeadProvider:
    provider_id = "test-memory4-w04-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"memory4-w04-test-provider-key-v1"):
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
            raise MemoryProtectionError("W04 fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("W04 fixture authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


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


def body(text: str, source_ref: str) -> dict[str, str]:
    return {
        "user_text": text,
        "assistant_text": "Noteret.",
        "source_ref": source_ref,
    }


async def canonical_extract(turn):
    return (
        MemoryCandidate(
            subject="user",
            predicate="verbatim_user_statement",
            value=turn.user_text,
            kind="note",
            sensitivity="private",
            source_type="user_explicit",
            source_ref=turn.source_ref,
            confidence=1.0,
            review_status="confirmed",
            evidence=turn.user_text,
        ),
    )


# Flag-off is independent from every earlier Memory4/Agent3 activation flag and
# returns before provider construction or database creation.
class MustNotBeConstructed:
    def __init__(self):
        raise AssertionError("W04 flag-off must not construct a provider")


with tempfile.TemporaryDirectory(prefix="memory4-w04-off-") as raw:
    db = Path(raw) / "must-not-exist.db"
    app = FastAPI()
    before_routes = len(app.router.routes)
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED=None,
        KALIV_MEMORY4_CONTEXT_ENABLED="1",
        KALIV_MEMORY4_CHAT_ENABLED="1",
        KALIV_AGENT3_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mounted = mount_memory4_write(
            app,
            protected_provider_factory=MustNotBeConstructed,
        )
    check(
        mounted is False
        and len(app.router.routes) == before_routes
        and not db.exists()
        and getattr(app.state, "memory4_write_mounted", False) is False,
        "W04 flag-off mounts nothing and opens no writer/provider independently",
    )

# Exact opt-in with no injected extractor binds the surface to the existing local
# W01 adapter. Merely mounting does not call Ollama.
with tempfile.TemporaryDirectory(prefix="memory4-w04-local-adapter-") as raw:
    db = Path(raw) / "memory.db"
    app = FastAPI()
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mounted = mount_memory4_write(app)
        service = getattr(app.state, "memory4_write_service", None)
        bound_extract = getattr(service, "_extract", None)
        check(
            mounted
            and callable(bound_extract)
            and getattr(bound_extract, "__name__", "") == "extract_memory_candidates_local",
            "W04 production mount defaults to the existing local-only W01 extractor",
        )
        close_memory4_write(app)

# Loopback admission is fail-closed before extraction/storage.
with tempfile.TemporaryDirectory(prefix="memory4-w04-loopback-") as raw:
    db = Path(raw) / "memory.db"
    extract_calls = 0

    async def counted_extract(_turn):
        global extract_calls
        extract_calls += 1
        return ()

    app = FastAPI()
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(
            app,
            loopback_allowed=lambda _request: False,
            extract_candidates=counted_extract,
        )
        with TestClient(app) as client:
            response = client.post(
                "/experimental/memory4/completed-turn",
                json=body("loopback denial", "conversation:w04-denied"),
            )
        check(
            response.status_code == 403 and extract_calls == 0,
            "W04 denies non-loopback calls before extraction/storage",
        )
        close_memory4_write(app)

# Strict request body, empty/no-store behavior and value-free response.
with tempfile.TemporaryDirectory(prefix="memory4-w04-strict-") as raw:
    db = Path(raw) / "memory.db"

    async def empty_extract(_turn):
        return ()

    app = FastAPI()
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(app, extract_candidates=empty_extract)
        with TestClient(app) as client:
            unknown = client.post(
                "/experimental/memory4/completed-turn",
                json={**body("strict", "conversation:w04-strict"), "extra": "no"},
            )
            wrong_type = client.post(
                "/experimental/memory4/completed-turn",
                json={
                    "user_text": 123,
                    "assistant_text": "Noteret.",
                    "source_ref": "conversation:w04-strict",
                },
            )
            secret_text = "private W04 value 4a6d"
            empty = client.post(
                "/experimental/memory4/completed-turn",
                json=body(secret_text, "conversation:w04-empty"),
            )
        empty_json = json.dumps(empty.json(), ensure_ascii=False)
        check(
            unknown.status_code == 422 and wrong_type.status_code == 422,
            "W04 request body rejects unknown fields and non-string types",
        )
        check(
            empty.status_code == 200
            and empty.json()["candidate_count"] == 0
            and empty.json()["sent_to_store"] is False
            and secret_text not in empty_json
            and "conversation:w04-empty" not in empty_json,
            "W04 empty extraction is no-store and response is value/provenance free",
        )
        close_memory4_write(app)

# Legacy route composes W01/W03/W02 create then exact dedupe.
with tempfile.TemporaryDirectory(prefix="memory4-w04-legacy-") as raw:
    db = Path(raw) / "memory.db"
    app = FastAPI()
    text = "Jeg bruger W04 legacy test 7c91"
    source_ref = "conversation:w04-legacy"
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(app, extract_candidates=canonical_extract)
        with TestClient(app) as client:
            created = client.post(
                "/experimental/memory4/completed-turn",
                json=body(text, source_ref),
            )
            deduped = client.post(
                "/experimental/memory4/completed-turn",
                json=body(text, source_ref),
            )
        check(
            created.status_code == 200
            and created.json()["created_count"] == 1
            and deduped.status_code == 200
            and deduped.json()["created_count"] == 0
            and deduped.json()["deduped_count"] == 1
            and deduped.json()["deduped_ids"] == created.json()["created_ids"],
            "W04 legacy surface creates then exact-dedupes through W03",
        )
        close_memory4_write(app)

# Operational failure messages are bounded/generic and never reflect private text.
with tempfile.TemporaryDirectory(prefix="memory4-w04-failure-") as raw:
    db = Path(raw) / "memory.db"
    leaked = "secret-material-must-not-escape-54ac"

    async def failing_extract(_turn):
        raise RuntimeError(leaked)

    app = FastAPI()
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(app, extract_candidates=failing_extract)
        with TestClient(app) as client:
            failed_response = client.post(
                "/experimental/memory4/completed-turn",
                json=body(leaked, "conversation:w04-failure"),
            )
        response_text = failed_response.text
        check(
            failed_response.status_code == 503
            and failed_response.json() == {"detail": "memory write unavailable"}
            and leaked not in response_text
            and "RuntimeError" not in response_text,
            "W04 operational failures return a generic 503 without private leakage",
        )
        close_memory4_write(app)

# Protected W04 requires the already-completed protection migration, writes only
# through LOCAL_MANAGEMENT, and deliberately does not create the #1218 sidecar.
with tempfile.TemporaryDirectory(prefix="memory4-w04-protected-") as raw:
    db = Path(raw) / "memory.db"
    bootstrap = MemoryStore(str(db))
    bootstrap.close()
    provider = TestAeadProvider()
    codec = MemoryProtectionCodec(provider)
    check(
        MemoryProtectionMigrator(db, codec).migrate().complete,
        "W04 protected fixture migration completes",
    )

    app = FastAPI()
    protected_text = "W04 protected statement 8b73"
    protected_source = "conversation:w04-protected"
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(
            app,
            protected_provider_factory=TestAeadProvider,
            extract_candidates=canonical_extract,
        )
        with TestClient(app) as client:
            protected_response = client.post(
                "/experimental/memory4/completed-turn",
                json=body(protected_text, protected_source),
            )
        created_id = protected_response.json()["created_ids"][0]
        close_memory4_write(app)

    with ProtectedMemoryReader(db, MemoryProtectionCodec(TestAeadProvider())) as reader:
        opened = reader.get(created_id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
    conn = sqlite3.connect(db)
    try:
        raw_row = conn.execute(
            "SELECT value,source_ref,protection_state FROM agent_memories WHERE id=?",
            (created_id,),
        ).fetchone()
        sidecar = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='agent_memory_protected_verbatim_lookup'"
        ).fetchone()
    finally:
        conn.close()
    check(
        protected_response.status_code == 200
        and opened.value == protected_text
        and opened.source_ref == protected_source
        and raw_row is not None
        and raw_row[0] == ""
        and raw_row[1] is None
        and raw_row[2] == "protected",
        "W04 protected surface uses migrated encrypted LOCAL_MANAGEMENT storage",
    )
    check(
        sidecar is None,
        "W04-A protected surface does not create or repair the blind-index sidecar",
    )

# Mount failure rolls routes/state back deterministically and closes no phantom
# resource. This also proves provider errors are reached only after explicit opt-in.
with tempfile.TemporaryDirectory(prefix="memory4-w04-rollback-") as raw:
    db = Path(raw) / "memory.db"
    bootstrap = MemoryStore(str(db))
    bootstrap.close()
    app = FastAPI()
    before_routes = len(app.router.routes)

    def failing_provider():
        raise RuntimeError("provider construction failed")

    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        try:
            mount_memory4_write(app, protected_provider_factory=failing_provider)
        except RuntimeError:
            rollback_failed = False
        else:
            rollback_failed = True
    check(
        not rollback_failed
        and len(app.router.routes) == before_routes
        and getattr(app.state, "memory4_write_substrate_writer", None) is None
        and getattr(app.state, "memory4_write_mounted", False) is False,
        "W04 mount failure rolls back routes and process-owned writer state",
    )

# Production lifecycle keeps scheduler ownership (__wrapped__) while closing the
# process-owned W04 writer on shutdown.
with tempfile.TemporaryDirectory(prefix="memory4-w04-cleanup-") as raw:
    db = Path(raw) / "memory.db"
    app = FastAPI()
    with environment(
        KALIV_MEMORY4_WRITE_ENABLED="1",
        KALIV_AGENT3_MEMORY_STORE="legacy",
        KALIV_AGENT3_MEMORY_DB=str(db),
    ):
        mount_memory4_write(app, extract_candidates=canonical_extract)
        writer = getattr(app.state, "memory4_write_substrate_writer", None)
        lifecycle_events: list[str] = []

        @asynccontextmanager
        async def inner(_app):
            lifecycle_events.append("enter")
            yield
            lifecycle_events.append("exit")

        composed = compose_memory4_context_lifespan(
            inner,
            extra_cleanup=close_memory4_write,
        )

        async def run_lifespan():
            async with composed(app):
                lifecycle_events.append("body")

        asyncio.run(run_lifespan())
        closed = False
        if writer is not None:
            try:
                writer._conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                closed = True
        check(
            getattr(composed, "__wrapped__", None) is inner
            and lifecycle_events == ["enter", "body", "exit"]
            and getattr(app.state, "memory4_write_substrate_writer", None) is None
            and closed,
            "W04 shutdown cleanup preserves scheduler wrapper ownership and closes writer",
        )

print(f"\n===== MEMORY 4 W04 WRITE SURFACE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
