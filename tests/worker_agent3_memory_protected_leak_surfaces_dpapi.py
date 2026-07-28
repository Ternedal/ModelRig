#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_leak_gate import build_leak_report  # noqa: E402
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from app.agent3.memory_protected_writer import (  # noqa: E402
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)
from app.agent3.memory_protection import (  # noqa: E402
    MemoryProtectionCodec,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


if os.name != "nt":
    print("SKIP: real protected-memory leak gate requires Windows DPAPI")
    raise SystemExit(0)

CANARIES = (
    "T033-DPAPI-LEAK-PRIVATE-8f3157b2",
    "T033-DPAPI-LEAK-PRIVATE-SOURCE-904268c3",
    "T033-DPAPI-LEAK-SECRET-a15379d4",
    "T033-DPAPI-LEAK-SECRET-SOURCE-b2648ae5",
)
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


with tempfile.TemporaryDirectory(prefix="kaliv-t033-dpapi-leak-") as tmp:
    root = Path(tmp)
    database = root / "memory.db"
    store = MemoryStore(str(database))
    try:
        store.create(
            subject="Anders",
            predicate="dpapi_leak_seed",
            value=CANARIES[0],
            sensitivity="private",
            source_ref=CANARIES[1],
        )
    finally:
        store.close()

    codec = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())
    summary = MemoryProtectionMigrator(database, codec).migrate()
    check("real DPAPI migration completes", summary.complete)

    writer = ProtectedMemoryWriter(
        database,
        MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        id_factory=lambda: "dpapi-leak-secret-001",
        clock=lambda: 3_000.0,
    )
    secret = writer.create(
        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        predicate="dpapi_leak_secret",
        value=CANARIES[2],
        sensitivity="secret",
        source_ref=CANARIES[3],
    )
    writer.close()

    with ProtectedMemoryReader(
        database,
        MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
    ) as reader:
        status = reader.status.to_dict()
        secret_metadata = reader.get(
            secret.id,
            access=MemoryReadAccess.METADATA_ONLY,
        ).to_dict()
        opened = reader.get(
            secret.id,
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )

    check(
        "same Windows user can reopen protected secret and provenance",
        opened.value == CANARIES[2] and opened.source_ref == CANARIES[3],
    )
    check(
        "DPAPI metadata surface remains redacted",
        secret_metadata["value"] == "[redacted]"
        and secret_metadata["source_ref"] is None,
    )

    backup_path = root / "memory-backup.db"
    backup(database, backup_path)
    report = build_leak_report(
        database=database,
        canaries=CANARIES,
        surfaces={
            "reader_status": status,
            "metadata_preview": secret_metadata,
            "logs": "",
            "planner_preview": {"protected_store_mounted": False},
            "outcome_context": {"protected_store_mounted": False},
            "embedding_projection": {"mode": "none"},
        },
        repository_root=ROOT,
        backups=(backup_path,),
    )
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    check("real DPAPI leak report passes", report["success"] is True)
    check("real DPAPI report remains non-activating", report["production_activation"] is False)
    check(
        "real DPAPI report and SQLite backup contain no plaintext canary",
        all(value not in rendered for value in CANARIES),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 WINDOWS DPAPI LEAK SURFACES: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
