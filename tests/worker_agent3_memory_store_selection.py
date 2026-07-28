#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_gateway import (  # noqa: E402
    MEMORY_GRANT_DB_ENV,
    MEMORY_GRANT_HEADER,
    MEMORY_GRANT_SCHEMA,
    MEMORY_STORE_ATTESTATION_HEADER,
    MEMORY_STORE_ATTESTATION_VALUE,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402
from app.agent3.production_mount import mount_agent3  # noqa: E402

SECRET = b"t033-protected-memory-gateway-test-secret-0123456789"
DOMAIN = MEMORY_GRANT_SCHEMA.encode("ascii") + b"\x00"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


class TestAeadProvider:
    provider_id = "test-protected-selection-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-selection-provider-key-not-production"):
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
            raise MemoryProtectionError("selection fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("selection fixture authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def grant_token(
    *,
    action: str,
    request_id: str,
    method: str,
    path: str,
    nonce: bytes,
    now: int,
    query: str = "",
    body_sha256: str = EMPTY_SHA256,
) -> str:
    claims = {
        "schema": MEMORY_GRANT_SCHEMA,
        "nonce": b64(nonce),
        "device_id": "paired-device-selection",
        "action": action,
        "request_id": request_id,
        "method": method,
        "path": path,
        "query": query,
        "body_sha256": body_sha256,
        "issued_at": now - 1,
        "expires_at": now + 30,
    }
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    payload_part = b64(payload)
    signature = hmac.new(
        SECRET,
        DOMAIN + payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return payload_part + "." + b64(signature)


@contextmanager
def configured(tmp: Path, *, mode: str | None, secret: bytes | None = SECRET):
    names = {
        "KALIV_AGENT3_ENABLED": "1",
        "KALIV_AGENT3_DB": str(tmp / "runs.db"),
        "KALIV_AGENT3_REVIEW_DB": str(tmp / "reviews.db"),
        "KALIV_AGENT3_REPLAN_DB": str(tmp / "replans.db"),
        "KALIV_AGENT3_MEMORY_DB": str(tmp / "memory.db"),
        MEMORY_GRANT_DB_ENV: str(tmp / "memory-grants.db"),
        "KALIV_AGENT3_PLAN_DB": str(tmp / "plans.db"),
        "KALIV_AGENT3_APPROVAL_DB": str(tmp / "approvals.db"),
    }
    if mode is not None:
        names["KALIV_AGENT3_MEMORY_STORE"] = mode
    if secret is not None:
        names["KALIV_AGENT3_MEMORY_API_SECRET"] = secret.decode("ascii")
    touched = set(names) | {
        "KALIV_AGENT3_MEMORY_STORE",
        "KALIV_AGENT3_MEMORY_API_SECRET",
        MEMORY_GRANT_DB_ENV,
    }
    old = {name: os.environ.get(name) for name in touched}
    try:
        for name in touched:
            os.environ.pop(name, None)
        os.environ.update(names)
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


with tempfile.TemporaryDirectory(prefix="kaliv-t033-selection-protected-") as raw:
    tmp = Path(raw)
    memory_path = tmp / "memory.db"
    grant_path = tmp / "memory-grants.db"
    legacy = MemoryStore(str(memory_path))
    try:
        legacy.create(
            subject="Anders",
            predicate="selection_private",
            value="T033-SELECTION-PRIVATE-PLAINTEXT",
            sensitivity="private",
        )
    finally:
        legacy.close()
    summary = MemoryProtectionMigrator(
        memory_path,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(summary.complete, "protected selection fixture migration completes")

    with configured(tmp, mode="protected"):
        app = FastAPI()
        check(
            mount_agent3(app, protected_provider_factory=TestAeadProvider),
            "explicit protected mode mounts successfully after completed migration",
        )
        check(
            app.state.agent3_memory_store_mode == "protected"
            and app.state.agent3_memory_store is None
            and app.state.agent3_protected_memory_reader is not None
            and app.state.agent3_protected_memory_writer is not None,
            "protected mode installs reader/writer and no legacy MemoryStore",
        )
        check(
            app.state.agent3_planner_memory_enabled is False,
            "legacy plaintext planner memory is deliberately disabled in protected mode",
        )
        check(
            Path(app.state.agent3_protected_memory_grant_db) == grant_path,
            "protected mode selects the exact separate grant ledger path",
        )
        paths = set(app.openapi()["paths"])
        check(
            "/experimental/agent3/memory/status" in paths
            and "/experimental/agent3/memory/search" in paths
            and "/experimental/agent3/memory/{memory_id}/correct" in paths,
            "protected metadata/write routes are mounted",
        )
        check(
            "/experimental/agent3/memory/context-preview" not in paths,
            "legacy context-preview route is absent in protected mode",
        )

        client = TestClient(app)
        no_grant = client.get(
            "/experimental/agent3/memory/status",
            headers={"X-Request-ID": "req-no-grant"},
        )
        check(
            no_grant.status_code == 403
            and no_grant.headers.get(MEMORY_STORE_ATTESTATION_HEADER)
            == MEMORY_STORE_ATTESTATION_VALUE,
            "direct worker request without gateway grant is refused and attested protected",
        )

        import time as _time

        request_id = "req-selection-status"
        path = "/experimental/agent3/memory/status"
        token = grant_token(
            action="status",
            request_id=request_id,
            method="GET",
            path=path,
            nonce=b"t" * 32,
            now=int(_time.time()),
        )
        response = client.get(
            path,
            headers={
                "X-Request-ID": request_id,
                MEMORY_GRANT_HEADER: token,
            },
        )
        check(
            response.status_code == 200
            and response.json()["protected_memory"]["production_activation"] is False
            and response.headers.get(MEMORY_STORE_ATTESTATION_HEADER)
            == MEMORY_STORE_ATTESTATION_VALUE,
            "gateway-signed status request reaches only the attested protected router",
        )
        check(
            grant_path.is_file() and grant_path.stat().st_size > 0,
            "protected grant ledger is created independently of the memory database",
        )
        reader = app.state.agent3_protected_memory_reader
        writer = app.state.agent3_protected_memory_writer
        writer.close()
        reader.close()


with tempfile.TemporaryDirectory(prefix="kaliv-t033-selection-incomplete-") as raw:
    tmp = Path(raw)
    legacy = MemoryStore(str(tmp / "memory.db"))
    try:
        legacy.create(
            subject="Anders",
            predicate="unmigrated_private",
            value="MUST-BLOCK-PROTECTED-STARTUP",
            sensitivity="private",
        )
    finally:
        legacy.close()
    with configured(tmp, mode="protected"):
        app = FastAPI()
        try:
            mount_agent3(app, protected_provider_factory=TestAeadProvider)
        except Exception:
            check(True, "incomplete migration aborts protected startup")
        else:
            check(False, "incomplete migration aborts protected startup")
        check(
            getattr(app.state, "agent3_memory_store", None) is None
            and not getattr(app.state, "agent3_full_surface_mounted", False),
            "failed protected startup does not instantiate or report legacy fallback",
        )


with tempfile.TemporaryDirectory(prefix="kaliv-t033-selection-secret-") as raw:
    tmp = Path(raw)
    provider_calls = 0

    def counted_provider():
        global provider_calls
        provider_calls += 1
        return TestAeadProvider()

    with configured(tmp, mode="protected", secret=None):
        app = FastAPI()
        try:
            mount_agent3(app, protected_provider_factory=counted_provider)
        except Exception:
            check(True, "missing gateway secret aborts protected startup")
        else:
            check(False, "missing gateway secret aborts protected startup")
        check(
            provider_calls == 0,
            "secret failure occurs before provider or database selection",
        )


with tempfile.TemporaryDirectory(prefix="kaliv-t033-selection-legacy-") as raw:
    tmp = Path(raw)
    with configured(tmp, mode=None, secret=None):
        app = FastAPI()
        check(mount_agent3(app), "unset mode preserves explicit legacy compatibility")
        paths = set(app.openapi()["paths"])
        check(
            app.state.agent3_memory_store_mode == "legacy"
            and type(app.state.agent3_memory_store).__name__ == "MemoryStore"
            and app.state.agent3_planner_memory_enabled is True
            and app.state.agent3_protected_memory_grant_db is None,
            "legacy mode retains existing store/planner and creates no grant ledger",
        )
        check(
            "/experimental/agent3/memory/context-preview" in paths
            and "/experimental/agent3/memory/status" not in paths,
            "legacy and protected route surfaces cannot be mounted together",
        )
        check(
            not (tmp / "memory-grants.db").exists(),
            "legacy mode does not create protected replay state",
        )
        app.state.agent3_memory_store.close()


with tempfile.TemporaryDirectory(prefix="kaliv-t033-selection-invalid-") as raw:
    tmp = Path(raw)
    with configured(tmp, mode="auto"):
        app = FastAPI()
        try:
            mount_agent3(app, protected_provider_factory=TestAeadProvider)
        except Exception:
            check(True, "unknown store mode aborts startup")
        else:
            check(False, "unknown store mode aborts startup")
        check(
            getattr(app.state, "agent3_memory_store", None) is None,
            "unknown mode cannot silently choose legacy",
        )

print(f"\n===== AGENT3 MEMORY STORE SELECTION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
