from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import memory as memory_package
from app.agent3.memory import MemoryStore
from app.agent3.memory_api import build_memory_router
from app.agent3.memory_context import MemoryContextCompiler
from app.agent3.memory_legacy_reader import LegacyMemoryReadError, LegacyMemoryReader
from app.agent3.memory_protection import KEY_SCOPE_CURRENT_USER, MemoryProtectionCodec
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.memory import HybridMemoryRetriever, SharedMemoryReader
from app.memory.context_api import build_memory4_context_router
from app.memory.context_mount import (
    MEMORY4_CONTEXT_FLAG,
    MEMORY4_SEMANTIC_FLAG,
    close_memory4_context,
    compose_memory4_context_lifespan,
    mount_memory4_context,
)
from app.memory.context_service import (
    CONTEXT_RECEIPT_SCHEMA,
    CONTEXT_SERVICE_SCHEMA,
    ContextForTurnRequest,
    MemoryContextForTurnService,
    MemoryContextServiceError,
)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


store = MemoryStore(os.path.join(tempfile.mkdtemp(prefix="agent3-memory-api-"), "memory.db"))
app = FastAPI()
app.include_router(build_memory_router(store))
client = TestClient(app)
headers = {"X-Request-ID": "req-memory-test"}

created_resp = client.post(
    "/experimental/agent3/memory",
    headers=headers,
    json={
        "subject": "anders",
        "predicate": "foretrækker_mad",
        "value": "ingen fisk",
        "kind": "preference",
        "sensitivity": "private",
    },
)
check(created_resp.status_code == 200, "explicit memory can be created through API")
created = created_resp.json()["memory"]
memory_id = created["id"]
check(created["review_status"] == "confirmed", "API-created memory is explicit and confirmed")
check(created["source_ref"] == "memory-api:req-memory-test", "API provenance is server-owned request id")

listed = client.get("/experimental/agent3/memory?subject=anders").json()["memories"]
check([item["id"] for item in listed] == [memory_id], "memory list supports subject filter")
searched = client.get("/experimental/agent3/memory/search?q=fisk").json()["memories"]
check([item["id"] for item in searched] == [memory_id], "memory search returns confirmed match")
check(client.get(f"/experimental/agent3/memory/{memory_id}").json()["memory"]["value"] == "ingen fisk", "memory get returns value")

corrected_resp = client.post(
    f"/experimental/agent3/memory/{memory_id}/correct",
    headers={"X-Request-ID": "req-correction"},
    json={"value": "ingen fisk eller sushi"},
)
check(corrected_resp.status_code == 200, "memory can be corrected through API")
corrected = corrected_resp.json()["memory"]
check(corrected["supersedes_id"] == memory_id, "correction creates a new version")
check(corrected["source_ref"] == "memory-api:req-correction", "correction has fresh provenance")
history = client.get(f"/experimental/agent3/memory/{corrected['id']}/history").json()["memories"]
check([item["lifecycle_status"] for item in history] == ["superseded", "active"], "history exposes both versions")

pending = store.create(
    subject="anders",
    predicate="mulig_præference",
    value="qwen",
    source_type="inferred",
    sensitivity="operational",
)
check(client.post(f"/experimental/agent3/memory/{pending.id}/confirm").status_code == 200, "pending internal proposal can be confirmed")
check(store.get(pending.id).review_status == "confirmed", "confirm endpoint changes review state")

pending_reject = store.create(
    subject="anders",
    predicate="forkert_præference",
    value="fisk",
    source_type="tool_observation",
)
check(client.post(f"/experimental/agent3/memory/{pending_reject.id}/reject").status_code == 200, "pending proposal can be rejected")
check(store.get(pending_reject.id).review_status == "rejected", "reject endpoint changes review state")

secret_create = client.post(
    "/experimental/agent3/memory",
    json={
        "subject": "anders",
        "predicate": "password",
        "value": "do-not-store-remotely",
        "sensitivity": "secret",
    },
)
check(secret_create.status_code == 422, "remote API refuses new secret memories")
secret = store.create(
    subject="anders",
    predicate="local_secret",
    value="hidden",
    sensitivity="secret",
)
secret_get = client.get(f"/experimental/agent3/memory/{secret.id}").json()["memory"]
check(secret_get["value"] == "[redacted]" and secret_get["source_ref"] is None, "existing local secret is redacted over API")
check(secret.id not in {item["id"] for item in client.get("/experimental/agent3/memory").json()["memories"]}, "secret rows are excluded from API listing")

expired = store.create(
    subject="anders",
    predicate="temporary",
    value="old",
    sensitivity="operational",
    expires_at=time.time() - 1,
)
normal_ids = {item["id"] for item in client.get("/experimental/agent3/memory").json()["memories"]}
check(expired.id not in normal_ids, "expired rows are excluded by default")
all_ids = {item["id"] for item in client.get("/experimental/agent3/memory?include_expired=true").json()["memories"]}
check(expired.id in all_ids, "expired rows require explicit include flag")

rig_memory = store.create(
    subject="modelrig",
    predicate="gpu",
    value="RTX 3060 12GB",
    sensitivity="public",
    source_ref="conversation:must-not-leak",
)
local_preview = client.post(
    "/experimental/agent3/memory/context-preview",
    json={"target": "local", "max_chars": 50_000},
)
check(local_preview.status_code == 200, "local context preview is available")
local_context = local_preview.json()
check(local_context["sent_to_model"] is False, "preview never sends context to a model")
check(
    {corrected["id"], pending.id, rig_memory.id}.issubset(set(local_context["included_ids"])),
    "local preview includes confirmed private and non-private memories",
)
check(secret.id not in local_context["included_ids"], "context preview never includes secret memory")
check("conversation:must-not-leak" not in local_context["text"], "context preview strips source references")

cloud_preview = client.post(
    "/experimental/agent3/memory/context-preview",
    json={"target": "cloud", "max_chars": 50_000},
).json()
check(corrected["id"] not in cloud_preview["included_ids"], "cloud preview excludes private memory by default")
check(pending.id in cloud_preview["included_ids"] and rig_memory.id in cloud_preview["included_ids"], "cloud preview keeps operational and public memory")
cloud_private = client.post(
    "/experimental/agent3/memory/context-preview",
    json={"target": "cloud", "allow_private_cloud": True, "max_chars": 50_000},
).json()
check(corrected["id"] in cloud_private["included_ids"], "private memory enters cloud preview only with explicit consent")

subject_preview = client.post(
    "/experimental/agent3/memory/context-preview",
    json={"subjects": ["modelrig"], "max_chars": 50_000},
).json()
check(subject_preview["included_ids"] == [rig_memory.id], "context preview can be restricted to explicit subjects")
check(client.post(
    "/experimental/agent3/memory/context-preview",
    json={"subjects": ["modelrig", "modelrig"]},
).status_code == 422, "duplicate subject filters are rejected")
small_preview = client.post(
    "/experimental/agent3/memory/context-preview",
    json={"target": "local", "max_chars": 10},
).json()
check(small_preview["text"] == "" and small_preview["included_ids"] == [], "context preview enforces hard character budget")

# Delete only after preview assertions so the active corrected version is visible
# to the context compiler.
deleted_resp = client.delete(f"/experimental/agent3/memory/{corrected['id']}")
check(deleted_resp.status_code == 200, "memory can be deleted through API")
deleted = deleted_resp.json()["memory"]
check(deleted["lifecycle_status"] == "deleted" and deleted["value"] == "", "delete response is a redacted tombstone")
check(client.get("/experimental/agent3/memory/missing").status_code == 404, "missing memory returns 404")
check(client.post(f"/experimental/agent3/memory/{pending.id}/confirm").status_code == 409, "reconfirming a confirmed memory returns conflict")


# Memory 4.0 R04 acceptance lives in this existing test file deliberately: the
# generated CURRENT_STATE test inventory is itself a drift gate, so adding a new
# tests/*.py filename would change repository authority for no product reason.
@contextmanager
def r04_configured(**values: str | None):
    touched = set(values) | {
        MEMORY4_CONTEXT_FLAG,
        MEMORY4_SEMANTIC_FLAG,
        "KALIV_AGENT3_ENABLED",
        "KALIV_AGENT3_MEMORY_DB",
        "KALIV_AGENT3_MEMORY_STORE",
        "KALIV_AGENT3_MEMORY_API_SECRET",
        "KALIV_AGENT3_MEMORY_GRANT_DB",
    }
    old = {name: os.environ.get(name) for name in touched}
    try:
        for name in touched:
            os.environ.pop(name, None)
        for name, value in values.items():
            if value is not None:
                os.environ[name] = value
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class R04TestProtectionProvider:
    provider_id = "memory4-context-test-provider-v1"
    key_scope = KEY_SCOPE_CURRENT_USER
    _key = b"memory4-context-test-key-not-production"

    @classmethod
    def _stream(cls, entropy: bytes, length: int) -> bytes:
        result = bytearray()
        counter = 0
        while len(result) < length:
            result.extend(
                hashlib.sha256(
                    cls._key + entropy + counter.to_bytes(4, "big")
                ).digest()
            )
            counter += 1
        return bytes(result[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(plaintext))
        return bytes(left ^ right for left, right in zip(plaintext, stream))

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(ciphertext))
        return bytes(left ^ right for left, right in zip(ciphertext, stream))


def seed_r04(path: Path) -> dict[str, str]:
    fixture = MemoryStore(str(path))
    try:
        public = fixture.create(
            subject="modelrig",
            predicate="gpu",
            value="RTX 3060 12GB",
            sensitivity="public",
            source_ref="conversation:must-not-cross-r04",
        )
        private = fixture.create(
            subject="anders",
            predicate="madpraeference",
            value="ingen fisk",
            sensitivity="private",
        )
        secret_row = fixture.create(
            subject="anders",
            predicate="token",
            value="R04-SECRET-CANARY",
            sensitivity="secret",
        )
        pending_row = fixture.create(
            subject="modelrig",
            predicate="pending",
            value="R04-PENDING-CANARY",
            sensitivity="operational",
            source_type="inferred",
        )
        return {
            "public": public.id,
            "private": private.id,
            "secret": secret_row.id,
            "pending": pending_row.id,
        }
    finally:
        fixture.close()


def r04_service(reader: LegacyMemoryReader) -> MemoryContextForTurnService:
    return MemoryContextForTurnService(
        reader=SharedMemoryReader(
            mode="legacy",
            read_context=reader.context_records,
        ),
        retriever=HybridMemoryRetriever(),
        compiler=MemoryContextCompiler(),
    )


def expect_r04_service_error(label: str, awaitable, contains: str) -> None:
    try:
        asyncio.run(awaitable)
    except MemoryContextServiceError as exc:
        check(contains in str(exc), label)
    except Exception:
        check(False, label)
    else:
        check(False, label)


with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-") as raw:
    root = Path(raw)
    db = root / "memory.db"
    ids = seed_r04(db)
    reader = LegacyMemoryReader(db)
    check(
        not hasattr(reader, "create")
        and not hasattr(reader, "correct")
        and not hasattr(reader, "delete"),
        "R04 legacy substrate exposes no write API",
    )
    try:
        reader._conn.execute(  # noqa: SLF001
            "UPDATE agent_memories SET predicate='write-attempt'"
        )
    except sqlite3.OperationalError:
        check(True, "R04 legacy SQLite connection is query_only")
    else:
        check(False, "R04 legacy SQLite connection is query_only")

    service = r04_service(reader)
    local = asyncio.run(
        service.context_for_turn(
            ContextForTurnRequest(query="anders madpraeference")
        )
    )
    check(local.receipt.schema == CONTEXT_RECEIPT_SCHEMA, "R04 receipt is versioned")
    check(local.receipt.sent_to_model is False, "R04 receipt is explicitly pre-model")
    check(
        ids["private"] in local.receipt.included_ids
        and "ingen fisk" in local.context,
        "R04 local context can include relevant private memory",
    )
    check(
        "R04-SECRET-CANARY" not in local.context
        and "R04-PENDING-CANARY" not in local.context
        and "conversation:must-not-cross-r04" not in local.context,
        "R04 strips secret, pending and source-ref canaries",
    )
    local_bytes = local.context.encode("utf-8")
    check(
        local.receipt.context_sha256 == hashlib.sha256(local_bytes).hexdigest()
        and local.receipt.byte_count == len(local_bytes)
        and local.receipt.character_count == len(local.context),
        "R04 receipt binds exact returned context bytes",
    )

    cloud = asyncio.run(
        service.context_for_turn(
            ContextForTurnRequest(
                query="anders madpraeference modelrig gpu",
                target="cloud",
            )
        )
    )
    check(
        ids["private"] not in cloud.receipt.included_ids
        and "ingen fisk" not in cloud.context
        and ids["public"] in cloud.receipt.included_ids,
        "R04 cloud target cannot caller-grant private memory",
    )

    tiny = asyncio.run(
        service.context_for_turn(
            ContextForTurnRequest(query="modelrig", max_context_chars=1)
        )
    )
    check(
        tiny.context == ""
        and tiny.receipt.included_ids == ()
        and tiny.receipt.context_sha256 == hashlib.sha256(b"").hexdigest(),
        "R04 empty budget result still has exact empty-context receipt",
    )
    expect_r04_service_error(
        "R04 rejects non-canonical turn text",
        service.context_for_turn(ContextForTurnRequest(query=" modelrig")),
        "canonical",
    )

    r04_api = FastAPI()
    r04_api.include_router(build_memory4_context_router(service))
    with TestClient(r04_api) as r04_client:
        response = r04_client.post(
            "/experimental/memory4/context-for-turn",
            json={"query": "modelrig gpu"},
        )
        body = response.json()
        check(
            response.status_code == 200
            and body["schema"] == CONTEXT_SERVICE_SCHEMA
            and set(body) == {"schema", "context", "receipt"},
            "R04 API exposes only versioned context and receipt",
        )
        extra = r04_client.post(
            "/experimental/memory4/context-for-turn",
            json={
                "query": "anders madpraeference",
                "target": "cloud",
                "allow_private_cloud": True,
            },
        )
        check(
            extra.status_code == 422,
            "R04 API rejects caller-supplied private-cloud authority",
        )

    remote_api = FastAPI()
    remote_api.include_router(
        build_memory4_context_router(service, loopback_allowed=lambda _req: False)
    )
    with TestClient(remote_api) as remote_client:
        remote = remote_client.post(
            "/experimental/memory4/context-for-turn",
            json={"query": "modelrig"},
        )
        check(remote.status_code == 403, "R04 worker surface is loopback-only")
    reader.close()


# Default-off must neither register a route nor create the configured store.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-off-") as raw:
    missing = Path(raw) / "must-not-exist.db"
    with r04_configured(
        KALIV_MEMORY4_CONTEXT_ENABLED=None,
        KALIV_AGENT3_ENABLED="0",
        KALIV_AGENT3_MEMORY_DB=str(missing),
        KALIV_AGENT3_MEMORY_STORE="legacy",
    ):
        r04_app = FastAPI()
        before = tuple(r04_app.routes)
        check(mount_memory4_context(r04_app) is False, "R04 mount is default-off")
        check(
            tuple(r04_app.routes) == before and not missing.exists(),
            "flag-off R04 opens no route and creates no DB",
        )


# The same explicit lifespan composition used by production must close the R04
# substrate even though a custom worker lifespan owns startup/shutdown.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-life-") as raw:
    db = Path(raw) / "memory.db"
    ids = seed_r04(db)
    lifecycle_events: list[str] = []

    @asynccontextmanager
    async def inner_lifespan(_app):
        lifecycle_events.append("inner-start")
        try:
            yield
        finally:
            lifecycle_events.append("inner-stop")

    with r04_configured(
        KALIV_MEMORY4_CONTEXT_ENABLED="1",
        KALIV_AGENT3_ENABLED="0",
        KALIV_AGENT3_MEMORY_DB=str(db),
        KALIV_AGENT3_MEMORY_STORE="legacy",
    ):
        r04_app = FastAPI()
        check(
            mount_memory4_context(r04_app),
            "R04 legacy mount succeeds with Agent 3 disabled",
        )
        substrate = r04_app.state.memory4_context_substrate_reader
        r04_app.router.lifespan_context = compose_memory4_context_lifespan(
            inner_lifespan
        )
        with TestClient(r04_app) as r04_client:
            response = r04_client.post(
                "/experimental/memory4/context-for-turn",
                json={"query": "modelrig gpu"},
            )
            check(
                response.status_code == 200
                and ids["public"] in response.json()["receipt"]["included_ids"],
                "R04 production-shaped lifespan serves reviewed context",
            )
        check(
            lifecycle_events == ["inner-start", "inner-stop"]
            and getattr(r04_app.state, "memory4_context_mounted", True) is False,
            "R04 cleanup is composed after inner worker shutdown",
        )
        try:
            substrate.context_records()
        except LegacyMemoryReadError:
            check(True, "R04 production-shaped lifespan closes SQLite reader")
        else:
            check(False, "R04 production-shaped lifespan closes SQLite reader")


# Explicit opt-in with a missing store fails closed and leaves no partial route.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-missing-") as raw:
    missing = Path(raw) / "missing.db"
    with r04_configured(
        KALIV_MEMORY4_CONTEXT_ENABLED="1",
        KALIV_AGENT3_ENABLED="0",
        KALIV_AGENT3_MEMORY_DB=str(missing),
        KALIV_AGENT3_MEMORY_STORE="legacy",
    ):
        r04_app = FastAPI()
        before = tuple(r04_app.routes)
        try:
            mount_memory4_context(r04_app)
        except LegacyMemoryReadError:
            check(True, "R04 enabled mount fails closed when store is absent")
        else:
            check(False, "R04 enabled mount fails closed when store is absent")
        check(
            tuple(r04_app.routes) == before and not missing.exists(),
            "failed R04 mount creates neither route nor DB",
        )


# Protected composition uses the existing completed-migration query-only reader;
# it needs neither Agent 3 activation nor the protected HTTP gateway grant ledger.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-protected-") as raw:
    root = Path(raw)
    db = root / "memory.db"
    ids = seed_r04(db)
    migration = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(R04TestProtectionProvider()),
    ).migrate()
    check(migration.complete, "R04 protected fixture migration completes")
    grant_db = root / "grant-ledger-must-not-exist.db"
    with r04_configured(
        KALIV_MEMORY4_CONTEXT_ENABLED="1",
        KALIV_AGENT3_ENABLED="0",
        KALIV_AGENT3_MEMORY_DB=str(db),
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_API_SECRET=None,
        KALIV_AGENT3_MEMORY_GRANT_DB=str(grant_db),
    ):
        r04_app = FastAPI()
        check(
            mount_memory4_context(
                r04_app,
                protected_provider_factory=R04TestProtectionProvider,
            ),
            "R04 protected mount needs no Agent 3 activation/gateway secret",
        )
        with TestClient(r04_app) as r04_client:
            local = r04_client.post(
                "/experimental/memory4/context-for-turn",
                json={"query": "anders madpraeference", "target": "local"},
            )
            cloud = r04_client.post(
                "/experimental/memory4/context-for-turn",
                json={
                    "query": "anders madpraeference modelrig gpu",
                    "target": "cloud",
                },
            )
            check(
                local.status_code == 200
                and ids["private"] in local.json()["receipt"]["included_ids"],
                "R04 protected local path opens private value via protected reader",
            )
            check(
                cloud.status_code == 200
                and ids["private"] not in cloud.json()["receipt"]["included_ids"],
                "R04 protected cloud path does not decrypt private memory",
            )
            check(
                not grant_db.exists(),
                "R04 context read creates no protected gateway grant ledger",
            )
        close_memory4_context(r04_app)


# Semantic retrieval is server-owned opt-in, not request authority, and uses the
# R03 local adapter selected at mount time.
with tempfile.TemporaryDirectory(prefix="kaliv-memory4-r04-semantic-") as raw:
    db = Path(raw) / "memory.db"
    seed_r04(db)
    semantic_calls: list[str] = []

    async def fake_local_embed(text: str) -> list[float]:
        semantic_calls.append(text)
        return [1.0, 0.0, 0.0]

    original_embed = memory_package.embed_memory_text_local
    try:
        memory_package.embed_memory_text_local = fake_local_embed
        with r04_configured(
            KALIV_MEMORY4_CONTEXT_ENABLED="1",
            KALIV_MEMORY4_SEMANTIC_ENABLED="1",
            KALIV_AGENT3_ENABLED="0",
            KALIV_AGENT3_MEMORY_DB=str(db),
            KALIV_AGENT3_MEMORY_STORE="legacy",
        ):
            r04_app = FastAPI()
            check(
                mount_memory4_context(r04_app),
                "R04 semantic mode is a separate server-owned opt-in",
            )
            with TestClient(r04_app) as r04_client:
                response = r04_client.post(
                    "/experimental/memory4/context-for-turn",
                    json={"query": "graphics accelerator"},
                )
                check(
                    response.status_code == 200
                    and response.json()["receipt"]["semantic_enabled"] is True
                    and bool(semantic_calls),
                    "R04 semantic receipt reflects local embedding use",
                )
            close_memory4_context(r04_app)
    finally:
        memory_package.embed_memory_text_local = original_embed


client.close()
store.close()
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
