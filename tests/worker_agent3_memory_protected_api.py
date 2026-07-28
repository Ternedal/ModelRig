#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import itertools
import sqlite3
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_api import (  # noqa: E402
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
    ProtectedMemoryApiGrant,
    build_protected_memory_router,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from app.agent3.memory_protected_writer import ProtectedMemoryWriter  # noqa: E402
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class TestAeadProvider:
    provider_id = "test-protected-api-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-api-test-key-not-production"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        block = 0
        while len(result) < length:
            result.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(result[:length])

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
            raise MemoryProtectionError("API fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("API fixture ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


VALUES = {
    "seed_private": "T033-API-SEED-PRIVATE-07d4",
    "seed_secret": "T033-API-SEED-SECRET-18e5",
    "created": "T033-API-CREATED-PRIVATE-29f6",
    "created_source": "memory-api:req-create-001",
    "corrected": "T033-API-CORRECTED-PRIVATE-3a07",
    "corrected_source": "memory-api:req-correct-002",
    "stale": "T033-API-STALE-PRIVATE-4b18",
}

passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def family_bytes(path: Path) -> bytes:
    raw = bytearray()
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if candidate.is_file():
            raw.extend(candidate.read_bytes())
    return bytes(raw)


def row(path: Path, memory_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        value = conn.execute(
            "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
        ).fetchone()
        assert value is not None
        return value
    finally:
        conn.close()


def row_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        conn.close()


def request_headers(request_id: str) -> dict[str, str]:
    return {"X-Request-ID": request_id}


# The router has no implicit allow mode. Even constructing it requires a real
# callable authorizer, so production cannot accidentally opt in with None/True.
try:
    build_protected_memory_router(  # type: ignore[arg-type]
        None,
        None,
        authorizer=None,
    )
except ProtectedMemoryApiAuthorizationError:
    check(True, "protected API cannot be built without an explicit authorizer")
else:
    check(False, "protected API cannot be built without an explicit authorizer")


with tempfile.TemporaryDirectory(prefix="kaliv-t033-protected-api-") as tmp:
    db = Path(tmp) / "memory.db"
    legacy = MemoryStore(str(db))
    try:
        private_seed = legacy.create(
            subject="Anders",
            predicate="api_seed_private",
            value=VALUES["seed_private"],
            sensitivity="private",
        )
        secret_seed = legacy.create(
            subject="Anders",
            predicate="api_seed_secret",
            value=VALUES["seed_secret"],
            sensitivity="secret",
        )
        legacy.create(
            subject="ModelRig",
            predicate="public_state",
            value="PUBLIC-STATE",
            sensitivity="public",
        )
    finally:
        legacy.close()

    migration = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(migration.complete, "protected API fixture migration completes")

    reader = ProtectedMemoryReader(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    writer_ids = iter(
        [
            "api-created-001",
            "api-corrected-002",
            "api-stale-unused-003",
        ]
    )
    writer = ProtectedMemoryWriter(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: next(writer_ids),
        clock=lambda: float(next(writer_clock)),
    )

    now = 10_000.0
    writer_clock = itertools.count(20_000)
    mode = {"value": "ok"}
    calls: list[tuple[str, ProtectedMemoryApiAction]] = []

    def authorizer(request, action):
        request_id = request.headers.get("X-Request-ID", "")
        calls.append((request_id, action))
        if mode["value"] == "raise":
            raise RuntimeError("authorizer backend unavailable")
        if mode["value"] == "wrong_type":
            return True
        grant_action = (
            ProtectedMemoryApiAction.STATUS
            if mode["value"] == "wrong_action"
            else action
        )
        principal = "" if mode["value"] == "blank_principal" else "device:paired-1"
        grant_request = (
            "different-request"
            if mode["value"] == "wrong_request"
            else request_id
        )
        issued_at = now - 1
        expires_at = now + 30
        if mode["value"] == "expired":
            issued_at, expires_at = now - 60, now - 1
        elif mode["value"] == "future":
            issued_at, expires_at = now + 6, now + 30
        elif mode["value"] == "long_lived":
            issued_at, expires_at = now - 1, now + 121
        return ProtectedMemoryApiGrant(
            principal=principal,
            action=grant_action,
            request_id=grant_request,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    app = FastAPI()
    app.include_router(
        build_protected_memory_router(
            reader,
            writer,
            authorizer=authorizer,
            clock=lambda: now,
        )
    )
    client = TestClient(app)

    check(
        client.get("/experimental/agent3/memory/status").status_code == 403,
        "missing canonical request id fails before authorization",
    )
    status = client.get(
        "/experimental/agent3/memory/status",
        headers=request_headers("req-status-000"),
    )
    check(status.status_code == 200, "fresh request-bound status grant is accepted")
    status_body = status.json()["protected_memory"]
    check(
        status_body["query_only"] is True
        and status_body["production_activation"] is False,
        "status reports query-only storage and no production activation",
    )

    for bad_mode, label in (
        ("wrong_type", "boolean authorizer result is refused"),
        ("wrong_action", "grant is bound to the exact API action"),
        ("blank_principal", "grant requires a canonical principal"),
        ("wrong_request", "grant is bound to the exact request id"),
        ("expired", "expired grant is refused"),
        ("future", "future-dated grant is refused"),
        ("long_lived", "grant lifetime is capped"),
        ("raise", "authorizer failure is fail-closed"),
    ):
        mode["value"] = bad_mode
        response = client.get(
            "/experimental/agent3/memory/status",
            headers=request_headers(f"req-bad-{bad_mode}"),
        )
        check(response.status_code == 403, label)
    mode["value"] = "ok"

    created_response = client.post(
        "/experimental/agent3/memory",
        headers=request_headers("req-create-001"),
        json={
            "subject": "Anders",
            "predicate": "api_private_created",
            "value": VALUES["created"],
            "kind": "preference",
            "sensitivity": "private",
        },
    )
    check(created_response.status_code == 200, "authorized private create succeeds")
    created = created_response.json()["memory"]
    created_id = created["id"]
    check(
        created["value"] == "[redacted]" and created["source_ref"] is None,
        "create response never returns value or provenance plaintext",
    )
    created_row = row(db, created_id)
    check(
        created_row["value"] == ""
        and created_row["source_ref"] is None
        and created_row["protection_state"] == "protected",
        "API create commits only protected payload columns",
    )
    opened_created = reader.get(
        created_id,
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
    check(
        opened_created.value == VALUES["created"]
        and opened_created.source_ref == VALUES["created_source"],
        "local-management reader can open the protected API write",
    )

    secret_create = client.post(
        "/experimental/agent3/memory",
        headers=request_headers("req-secret-create"),
        json={
            "subject": "Anders",
            "predicate": "api_secret_forbidden",
            "value": "MUST-NOT-BE-REMOTE",
            "sensitivity": "secret",
        },
    )
    check(secret_create.status_code == 422, "remote boundary refuses secret creation")

    listed = client.get(
        "/experimental/agent3/memory?subject=Anders",
        headers=request_headers("req-list-001"),
    )
    listed_records = listed.json()["memories"]
    listed_ids = {item["id"] for item in listed_records}
    check(
        private_seed.id in listed_ids
        and created_id in listed_ids
        and secret_seed.id not in listed_ids,
        "list includes non-secret metadata and omits secret rows",
    )
    check(
        all(item["value"] == "[redacted]" and item["source_ref"] is None for item in listed_records),
        "list is metadata-only for public, operational and private rows",
    )

    value_search = client.get(
        f"/experimental/agent3/memory/search?q={VALUES['created']}",
        headers=request_headers("req-search-value"),
    ).json()["memories"]
    predicate_search = client.get(
        "/experimental/agent3/memory/search?q=api_private_created",
        headers=request_headers("req-search-metadata"),
    ).json()["memories"]
    check(value_search == [], "search never scans or decrypts protected values")
    check(
        [item["id"] for item in predicate_search] == [created_id]
        and predicate_search[0]["value"] == "[redacted]",
        "metadata search matches subject/predicate and still redacts payload",
    )

    get_created = client.get(
        f"/experimental/agent3/memory/{created_id}",
        headers=request_headers("req-get-created"),
    )
    check(
        get_created.status_code == 200
        and get_created.json()["memory"]["value"] == "[redacted]",
        "get returns only private metadata",
    )
    check(
        client.get(
            f"/experimental/agent3/memory/{secret_seed.id}",
            headers=request_headers("req-get-secret"),
        ).status_code
        == 404,
        "secret metadata is absent from the remote boundary even by id",
    )

    corrected_response = client.post(
        f"/experimental/agent3/memory/{created_id}/correct",
        headers=request_headers("req-correct-002"),
        json={
            "expected_updated_at": created["updated_at"],
            "value": VALUES["corrected"],
        },
    )
    check(corrected_response.status_code == 200, "CAS-bound private correction succeeds")
    corrected = corrected_response.json()["memory"]
    corrected_id = corrected["id"]
    check(
        corrected["value"] == "[redacted]"
        and corrected["source_ref"] is None
        and corrected["supersedes_id"] == created_id,
        "correction response is redacted and preserves lifecycle metadata",
    )
    opened_corrected = reader.get(
        corrected_id,
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
    check(
        opened_corrected.value == VALUES["corrected"]
        and opened_corrected.source_ref == VALUES["corrected_source"],
        "local-management reader opens the corrected encrypted value",
    )

    history = client.get(
        f"/experimental/agent3/memory/{corrected_id}/history",
        headers=request_headers("req-history-003"),
    ).json()["memories"]
    check(
        [item["lifecycle_status"] for item in history] == ["superseded", "active"]
        and all(item["value"] == "[redacted]" for item in history),
        "history exposes version metadata without either plaintext value",
    )

    count_before_stale = row_count(db)
    stale = client.post(
        f"/experimental/agent3/memory/{corrected_id}/correct",
        headers=request_headers("req-stale-004"),
        json={
            "expected_updated_at": corrected["updated_at"] - 1,
            "value": VALUES["stale"],
        },
    )
    check(stale.status_code == 409, "stale remote correction is rejected")
    check(
        row_count(db) == count_before_stale,
        "stale correction leaves no replacement row",
    )

    deleted_response = client.delete(
        f"/experimental/agent3/memory/{corrected_id}"
        f"?expected_updated_at={corrected['updated_at']}",
        headers=request_headers("req-delete-005"),
    )
    check(deleted_response.status_code == 200, "CAS-bound protected delete succeeds")
    deleted = deleted_response.json()["memory"]
    deleted_row = row(db, corrected_id)
    check(
        deleted["value"] == ""
        and deleted["source_ref"] is None
        and deleted["lifecycle_status"] == "deleted",
        "delete response is a payload-free tombstone",
    )
    check(
        deleted_row["value_protected"] is None
        and deleted_row["source_ref_protected"] is None
        and deleted_row["protection_state"] == "redacted",
        "delete removes both protected envelopes from storage",
    )

    raw = family_bytes(db)
    check(
        all(value.encode("utf-8") not in raw for value in VALUES.values()),
        "SQLite/WAL/journal family contains none of the protected API plaintext",
    )
    check(
        all(isinstance(action, ProtectedMemoryApiAction) for _, action in calls),
        "authorizer receives typed actions rather than free-form strings",
    )

    writer.close()
    reader.close()

# This slice is a boundary, not activation. The production mount must remain on
# the existing MemoryStore until an explicit store-selection slice wires the
# authenticated Go gateway and protected router together.
production_mount = (
    ROOT / "worker" / "app" / "agent3" / "production_mount.py"
).read_text(encoding="utf-8")
check(
    "memory_protected_api" not in production_mount
    and "build_protected_memory_router" not in production_mount,
    "protected API remains unmounted in production",
)

print(f"\n===== AGENT3 PROTECTED MEMORY API: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
