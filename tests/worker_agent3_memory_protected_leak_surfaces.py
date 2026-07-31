#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_leak_gate import (  # noqa: E402
    ProtectedMemoryLeakGateError,
    build_leak_report,
    scan_runtime_mounts,
    scan_sensitive_schema_objects,
    scan_sqlite_family,
    scan_surface,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from app.agent3.memory_protected_writer import (  # noqa: E402
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class TestAeadProvider:
    provider_id = "test-t033-leak-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-leak-gate-key-not-production"):
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
            raise MemoryProtectionError("leak fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("leak fixture authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


LEAK_MARKERS = {
    "seed_private": "T033-LEAK-SEED-PRIVATE-19cfa15b",
    "legacy_seed": "T033-LEAK-LEGACY-SEED-2ad0b26c",
    "local": "T033-LEAK-LOCAL-3be1c37d",
    "local_source": "T033-LEAK-LOCAL-SOURCE-4cf2d48e",
    "management": "T033-LEAK-MANAGEMENT-5d03e59f",
    "management_source": "T033-LEAK-MANAGEMENT-SOURCE-6e14f6a0",
}
ALL_MARKERS = tuple(LEAK_MARKERS.values())
checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def backup(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def serialized(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


with tempfile.TemporaryDirectory(prefix="kaliv-t033-leak-") as tmp:
    work = Path(tmp)
    database = work / "memory.db"
    store = MemoryStore(str(database))
    try:
        store.create(
            subject="Anders",
            predicate="leak_seed_private",
            value=LEAK_MARKERS["seed_private"],
            sensitivity="private",
        )
        store.create(
            subject="Anders",
            predicate="leak_legacy_seed",
            value=LEAK_MARKERS["legacy_seed"],
            sensitivity="secret",
        )
    finally:
        store.close()

    codec = MemoryProtectionCodec(TestAeadProvider())
    migrated = MemoryProtectionMigrator(database, codec).migrate()
    check("protected leak fixture migration completes", migrated.complete)

    writer = ProtectedMemoryWriter(
        database,
        MemoryProtectionCodec(TestAeadProvider()),
        id_factory=iter(("leak-private-001", "leak-secret-002")).__next__,
        clock=iter((2_000.0, 2_001.0)).__next__,
    )
    private_record = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        predicate="leak_local",
        value=LEAK_MARKERS["local"],
        sensitivity="private",
        source_ref=LEAK_MARKERS["local_source"],
    )
    management_record = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        predicate="leak_management",
        value=LEAK_MARKERS["management"],
        sensitivity="secret",
        source_ref=LEAK_MARKERS["management_source"],
    )
    writer.close()

    captured = io.StringIO()
    exception_surfaces: list[str] = []
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        with ProtectedMemoryReader(
            database,
            MemoryProtectionCodec(TestAeadProvider()),
        ) as reader:
            status = reader.status.to_dict()
            local_metadata = reader.get(
                private_record.id,
                access=MemoryReadAccess.METADATA_ONLY,
            ).to_dict()
            management_metadata = reader.get(
                management_record.id,
                access=MemoryReadAccess.METADATA_ONLY,
            ).to_dict()
            management_private = reader.get(
                private_record.id,
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
            )
            management_view = reader.get(
                management_record.id,
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
            )
            local_context = reader.context_records(
                access=MemoryReadAccess.LOCAL_CONTEXT,
                subjects=["Anders"],
                limit=50,
                max_chars=50_000,
            )
            try:
                reader.get(
                    private_record.id,
                    access="local_management",  # type: ignore[arg-type]
                )
            except Exception as exc:
                exception_surfaces.extend([str(exc), repr(exc)])

    check(
        "authorized local management opens private value and source",
        management_private.value == LEAK_MARKERS["local"]
        and management_private.source_ref == LEAK_MARKERS["local_source"],
    )
    check(
        "authorized local management opens secret value and source",
        management_view.value == LEAK_MARKERS["management"]
        and management_view.source_ref == LEAK_MARKERS["management_source"],
    )
    check(
        "metadata-only projection redacts protected values and provenance",
        local_metadata["value"] == "[redacted]"
        and local_metadata["source_ref"] is None
        and management_metadata["value"] == "[redacted]"
        and management_metadata["source_ref"] is None,
    )
    check(
        "local context opens private but never secret or source provenance",
        LEAK_MARKERS["local"] in [record.value for record in local_context]
        and LEAK_MARKERS["management"] not in [record.value for record in local_context]
        and all(record.source_ref is None for record in local_context),
    )

    receipt = {
        "requested": True,
        "sent_to_model": True,
        "target": "local",
        "included_ids": [private_record.id],
        "excluded_ids": [management_record.id],
        "character_count": len(LEAK_MARKERS["local"]),
        "sha256": hashlib.sha256(LEAK_MARKERS["local"].encode()).hexdigest(),
    }
    check(
        "planner memory receipt contains hash and count but no plaintext",
        receipt["sha256"] == hashlib.sha256(LEAK_MARKERS["local"].encode()).hexdigest()
        and LEAK_MARKERS["local"] not in serialized(receipt),
    )

    backup_path = work / "memory-backup.db"
    backup(database, backup_path)
    clean_surfaces = {
        "reader_status": status,
        "metadata_preview": [local_metadata, management_metadata],
        "planner_memory_receipt": receipt,
        "exception_messages": exception_surfaces,
        "captured_logs": captured.getvalue(),
        "embedding_projection": {
            "mode": "none",
            "indexed_fields": ["subject", "predicate", "updated_at"],
        },
        "outcome_projection": {
            "protected_store_mounted": False,
            "payload": None,
        },
    }
    report = build_leak_report(
        database=database,
        canaries=ALL_MARKERS,
        surfaces=clean_surfaces,
        repository_root=ROOT,
        backups=(backup_path,),
    )
    report_text = serialized(report)
    check("clean leak report passes", report["success"] is True and report["findings"] == [])
    check("leak report is non-activating", report["production_activation"] is False)
    check(
        "leak report stores only canary digests",
        all(value not in report_text for value in ALL_MARKERS)
        and set(report["canary_sha256s"])
        == {hashlib.sha256(value.encode()).hexdigest() for value in ALL_MARKERS},
    )
    check(
        "SQLite database WAL journal and backup contain no plaintext canary",
        scan_sqlite_family(
            database,
            canaries=ALL_MARKERS,
            backups=(backup_path,),
        )
        == [],
    )
    check(
        "SQLite has no sensitive value index trigger or view",
        scan_sensitive_schema_objects(database) == [],
    )
    check(
        "protected reader and writer remain absent from runtime mounts",
        scan_runtime_mounts(ROOT) == [],
    )

    leaked_surface = scan_surface(
        "mutated_preview",
        {"text": LEAK_MARKERS["local"]},
        canaries=ALL_MARKERS,
    )
    check(
        "surface mutation is caught without storing plaintext",
        len(leaked_surface) == 1
        and leaked_surface[0].canary_sha256
        == hashlib.sha256(LEAK_MARKERS["local"].encode()).hexdigest()
        and LEAK_MARKERS["local"] not in serialized(leaked_surface[0].to_dict()),
    )

    bad_backup = work / "tampered-backup.bin"
    bad_backup.write_bytes(b"prefix:" + LEAK_MARKERS["management"].encode() + b":suffix")
    backup_findings = scan_sqlite_family(
        database,
        canaries=ALL_MARKERS,
        backups=(bad_backup,),
    )
    check(
        "plaintext backup mutation is caught",
        any(
            finding.location == bad_backup.name
            and finding.canary_sha256
            == hashlib.sha256(LEAK_MARKERS["management"].encode()).hexdigest()
            for finding in backup_findings
        ),
    )

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE INDEX idx_t033_forbidden_value_projection ON agent_memories(value)"
        )
        connection.commit()
    finally:
        connection.close()
    schema_findings = scan_sensitive_schema_objects(database)
    check(
        "sensitive schema projection mutation is caught",
        any(
            finding.location == "idx_t033_forbidden_value_projection"
            and finding.kind == "sensitive_projection"
            for finding in schema_findings
        ),
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP INDEX idx_t033_forbidden_value_projection")
        connection.commit()
    finally:
        connection.close()

    fake_root = work / "fake-repository"
    fake_runtime = fake_root / "runtime.py"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text(
        "from app.agent3.memory_protected_reader import ProtectedMemoryReader\n",
        encoding="utf-8",
    )
    mount_findings = scan_runtime_mounts(fake_root, files=("runtime.py",))
    check(
        "implicit runtime mount mutation is caught",
        any(finding.kind == "implicit_mount" for finding in mount_findings),
    )

    try:
        scan_surface("duplicates", "clean", canaries=(ALL_MARKERS[0], ALL_MARKERS[0]))
    except ProtectedMemoryLeakGateError as exc:
        check("duplicate canaries fail closed", "unique" in str(exc))
    else:
        check("duplicate canaries fail closed", False)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 PROTECTED MEMORY LEAK SURFACES: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
