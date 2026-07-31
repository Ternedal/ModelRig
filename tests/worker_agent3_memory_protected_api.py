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
    MAX_PROTECTED_MEMORY_API_BODY_BYTES,
    ProtectedMemoryApiAction,
    ProtectedMemoryApiAuthorizationError,
    ProtectedMemoryApiGrant,
    build_protected_memory_router,
)
from app.agent3.memory_protected_leak_gate import (  # noqa: E402
    scan_runtime_mounts,
    scan_sqlite_family,
    scan_surface,
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
        out = bytearray()
        block = 0
        while len(out) < length:
            out.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(out[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.calls += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(a ^ b for a, b in zip(plaintext, stream))
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
        return bytes(a ^ b for a, b in zip(encrypted, stream))


API_MARKERS = {
    "seed_private": "T033-API-SEED-PRIVATE-07d4",
    "seed_management": "T033-API-SEED-MANAGEMENT-18e5",
    "created": "T033-API-CREATED-PRIVATE-29f6",
    "created_source": "memory-api:device:paired-1:req-create-001",
    "corrected": "T033-API-CORRECTED-PRIVATE-3a07",
    "corrected_source": "memory-api:device:paired-1:req-correct-002",
    "stale": "T033-API-STALE-PRIVATE-4b18",
    "invalid": "T033-API-INVALID-BODY-5c29",
    "unauthorized": "T033-API-UNAUTHORIZED-BODY-6d3a",
    "restricted": "T033-API-RESTRICTED-WRITE-7e4b",
    "oversized": "T033-API-OVERSIZED-BODY-8f5c",
}
ALL_MARKERS = tuple(API_MARKERS.values())

passed = failed = 0
response_surfaces: list[dict[str, object]] = []


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def capture(response):
    response_surfaces.append(
        {
            "status_code": response.status_code,
            "body": response.text,
        }
    )
    return response


def row(path: Path, memory_id: str) -> sqlite3.Row:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        result = connection.execute(
            "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
        ).fetchone()
        assert result is not None
        return result
    finally:
        connection.close()


def row_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(
            connection.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0]
        )
    finally:
        connection.close()


def headers(request_id: str) -> dict[str, str]:
    return {"X-Request-ID": request_id}


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
    database = Path(tmp) / "memory.db"
    legacy = MemoryStore(str(database))
    try:
        private_seed = legacy.create(
            subject="Anders",
            predicate="api_seed_private",
            value=API_MARKERS["seed_private"],
            sensitivity="private",
        )
        management_seed = legacy.create(
            subject="Anders",
            predicate="api_seed_management",
            value=API_MARKERS["seed_management"],
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

    summary = MemoryProtectionMigrator(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(summary.complete, "protected API fixture migration completes")

    reader = ProtectedMemoryReader(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    writer_clock = itertools.count(20_000)
    writer_ids = iter(
        [
            "api-created-001",
            "api-corrected-002",
            "api-stale-unused-003",
        ]
    )
    writer = ProtectedMemoryWriter(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=lambda: next(writer_ids),
        clock=lambda: float(next(writer_clock)),
    )

    now = 10_000.0
    mode = {"value": "ok"}
    calls: list[tuple[str, ProtectedMemoryApiAction]] = []

    def authorizer(request, action):
        request_id = request.headers.get("X-Request-ID", "")
        calls.append((request_id, action))
        if mode["value"] == "raise":
            raise RuntimeError("authorizer backend unavailable")
        if mode["value"] == "wrong_type":
            return True
        grant_action = action
        if mode["value"] == "wrong_action":
            grant_action = (
                ProtectedMemoryApiAction.READ_METADATA
                if action is not ProtectedMemoryApiAction.READ_METADATA
                else ProtectedMemoryApiAction.STATUS
            )
        principal = "" if mode["value"] == "blank_principal" else "device:paired-1"
        grant_request = (
            "different-request" if mode["value"] == "wrong_request" else request_id
        )
        issued_at, expires_at = now - 1, now + 30
        if mode["value"] == "expired":
            issued_at, expires_at = now - 60, now - 1
        elif mode["value"] == "future":
            issued_at, expires_at = now + 6, now + 30
        elif mode["value"] == "long_lived":
            issued_at, expires_at = now - 1, now + 121
        elif mode["value"] == "inverted":
            issued_at, expires_at = now + 4, now + 3
        elif mode["value"] == "boolean_time":
            issued_at, expires_at = True, now + 30
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

    missing_id = capture(client.get("/experimental/agent3/memory/status"))
    check(
        missing_id.status_code == 403
        and missing_id.json()["detail"] == "protected memory authorization denied",
        "missing canonical request id fails with a fixed public error",
    )

    status = capture(
        client.get(
            "/experimental/agent3/memory/status",
            headers=headers("req-status-000"),
        )
    )
    status_body = status.json()["protected_memory"]
    check(status.status_code == 200, "fresh request-bound status grant is accepted")
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
        ("inverted", "grant expiry must follow issuance"),
        ("boolean_time", "boolean grant timestamps are refused"),
        ("raise", "authorizer failure is fail-closed"),
    ):
        mode["value"] = bad_mode
        response = capture(
            client.get(
                "/experimental/agent3/memory/status",
                headers=headers(f"req-bad-{bad_mode}"),
            )
        )
        check(
            response.status_code == 403
            and response.json()["detail"] == "protected memory authorization denied",
            label,
        )
    mode["value"] = "ok"

    before_denied = row_count(database)
    mode["value"] = "raise"
    denied_body = capture(
        client.post(
            "/experimental/agent3/memory",
            headers=headers("req-denied-body"),
            json={
                "subject": "Anders",
                "predicate": "api_denied_body",
                "value": API_MARKERS["unauthorized"],
                "sensitivity": "private",
            },
        )
    )
    mode["value"] = "ok"
    check(
        denied_body.status_code == 403
        and API_MARKERS["unauthorized"] not in denied_body.text
        and row_count(database) == before_denied,
        "authorization fails before a private body is parsed or stored",
    )

    before_invalid = row_count(database)
    invalid_body = capture(
        client.post(
            "/experimental/agent3/memory",
            headers=headers("req-invalid-body"),
            json={
                "subject": "Anders",
                "predicate": "api_invalid_body",
                "value": {"marker": API_MARKERS["invalid"]},
                "sensitivity": "private",
            },
        )
    )
    check(
        invalid_body.status_code == 422
        and invalid_body.json()["detail"] == "protected memory request rejected"
        and API_MARKERS["invalid"] not in invalid_body.text
        and row_count(database) == before_invalid,
        "invalid JSON shape is rejected without Pydantic input echo or storage",
    )

    oversized_value = (
        API_MARKERS["oversized"]
        + "x" * (MAX_PROTECTED_MEMORY_API_BODY_BYTES + 1)
    )
    oversized_body = capture(
        client.post(
            "/experimental/agent3/memory",
            headers=headers("req-oversized-body"),
            json={
                "subject": "Anders",
                "predicate": "api_oversized_body",
                "value": oversized_value,
                "sensitivity": "private",
            },
        )
    )
    check(
        oversized_body.status_code == 422
        and API_MARKERS["oversized"] not in oversized_body.text
        and row_count(database) == before_invalid,
        "oversized request body fails closed without echo or mutation",
    )

    created_response = capture(
        client.post(
            "/experimental/agent3/memory",
            headers=headers("req-create-001"),
            json={
                "subject": "Anders",
                "predicate": "api_private_created",
                "value": API_MARKERS["created"],
                "kind": "preference",
                "sensitivity": "private",
            },
        )
    )
    created = created_response.json()["memory"]
    created_id = created["id"]
    check(created_response.status_code == 200, "authorized private create succeeds")
    check(
        created["value"] == "[redacted]" and created["source_ref"] is None,
        "create response never returns value or provenance plaintext",
    )
    created_row = row(database, created_id)
    check(
        created_row["value"] == ""
        and created_row["source_ref"] is None
        and created_row["protection_state"] == "protected",
        "API create commits only protected payload columns",
    )
    opened = reader.get(created_id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
    check(
        opened.value == API_MARKERS["created"]
        and opened.source_ref == API_MARKERS["created_source"],
        "local-management reader opens value and server-owned request provenance",
    )

    restricted_create = capture(
        client.post(
            "/experimental/agent3/memory",
            headers=headers("req-restricted-create"),
            json={
                "subject": "Anders",
                "predicate": "api_restricted_write",
                "value": API_MARKERS["restricted"],
                "sensitivity": "secret",
            },
        )
    )
    check(
        restricted_create.status_code == 422
        and API_MARKERS["restricted"] not in restricted_create.text,
        "remote boundary refuses local-management-only classification without echo",
    )

    listed_response = capture(
        client.get(
            "/experimental/agent3/memory?subject=Anders",
            headers=headers("req-list-001"),
        )
    )
    listed = listed_response.json()["memories"]
    listed_ids = {item["id"] for item in listed}
    check(
        private_seed.id in listed_ids
        and created_id in listed_ids
        and management_seed.id not in listed_ids,
        "list includes non-secret metadata and omits local-management-only rows",
    )
    check(
        all(
            item["value"] == "[redacted]" and item["source_ref"] is None
            for item in listed
        ),
        "list is metadata-only for public, operational and private rows",
    )

    value_search_response = capture(
        client.get(
            f"/experimental/agent3/memory/search?q={API_MARKERS['created']}",
            headers=headers("req-search-value"),
        )
    )
    metadata_search_response = capture(
        client.get(
            "/experimental/agent3/memory/search?q=api_private_created",
            headers=headers("req-search-metadata"),
        )
    )
    value_search = value_search_response.json()["memories"]
    metadata_search = metadata_search_response.json()["memories"]
    check(value_search == [], "search never scans or decrypts protected values")
    check(
        [item["id"] for item in metadata_search] == [created_id]
        and metadata_search[0]["value"] == "[redacted]",
        "metadata search matches subject or predicate and still redacts payload",
    )

    get_created = capture(
        client.get(
            f"/experimental/agent3/memory/{created_id}",
            headers=headers("req-get-created"),
        )
    )
    check(
        get_created.status_code == 200
        and get_created.json()["memory"]["value"] == "[redacted]",
        "get returns only private metadata",
    )
    get_management = capture(
        client.get(
            f"/experimental/agent3/memory/{management_seed.id}",
            headers=headers("req-get-management"),
        )
    )
    check(
        get_management.status_code == 404,
        "local-management-only metadata is absent remotely even by id",
    )

    corrected_response = capture(
        client.post(
            f"/experimental/agent3/memory/{created_id}/correct",
            headers=headers("req-correct-002"),
            json={
                "expected_updated_at": created["updated_at"],
                "value": API_MARKERS["corrected"],
            },
        )
    )
    corrected = corrected_response.json()["memory"]
    corrected_id = corrected["id"]
    check(
        corrected_response.status_code == 200,
        "CAS-bound private correction succeeds",
    )
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
        opened_corrected.value == API_MARKERS["corrected"]
        and opened_corrected.source_ref == API_MARKERS["corrected_source"],
        "local-management reader opens corrected value and provenance",
    )

    history_response = capture(
        client.get(
            f"/experimental/agent3/memory/{corrected_id}/history",
            headers=headers("req-history-003"),
        )
    )
    history = history_response.json()["memories"]
    check(
        [item["lifecycle_status"] for item in history]
        == ["superseded", "active"]
        and all(item["value"] == "[redacted]" for item in history),
        "history exposes version metadata without plaintext values",
    )

    before_stale = row_count(database)
    stale_response = capture(
        client.post(
            f"/experimental/agent3/memory/{corrected_id}/correct",
            headers=headers("req-stale-004"),
            json={
                "expected_updated_at": corrected["updated_at"] - 1,
                "value": API_MARKERS["stale"],
            },
        )
    )
    check(
        stale_response.status_code == 409
        and stale_response.json()["detail"] == "memory conflict",
        "stale remote correction is rejected with a fixed conflict response",
    )
    check(
        row_count(database) == before_stale,
        "stale correction leaves no replacement row",
    )

    deleted_response = capture(
        client.delete(
            f"/experimental/agent3/memory/{corrected_id}"
            f"?expected_updated_at={corrected['updated_at']}",
            headers=headers("req-delete-005"),
        )
    )
    deleted = deleted_response.json()["memory"]
    deleted_row = row(database, corrected_id)
    check(deleted_response.status_code == 200, "CAS-bound protected delete succeeds")
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

    check(
        scan_surface(
            "protected_api_responses",
            response_surfaces,
            canaries=ALL_MARKERS,
        )
        == [],
        "all status success validation denial and conflict responses are marker-free",
    )
    check(
        scan_sqlite_family(database, canaries=ALL_MARKERS) == [],
        "SQLite WAL SHM and journal contain none of the protected API markers",
    )
    check(
        all(isinstance(action, ProtectedMemoryApiAction) for _, action in calls),
        "authorizer receives typed actions rather than free-form strings",
    )

    writer.close()
    reader.close()

production_mount = (
    ROOT / "worker" / "app" / "agent3" / "production_mount.py"
).read_text(encoding="utf-8")
check(
    "memory_protected_api" not in production_mount
    and "build_protected_memory_router" not in production_mount,
    "protected API remains unmounted in production",
)
check(
    scan_runtime_mounts(ROOT) == [],
    "protected reader and writer remain absent from current runtime boundaries",
)

print(
    f"\n===== AGENT3 PROTECTED MEMORY API: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
