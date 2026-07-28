#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_context import ContextTarget  # noqa: E402
from app.agent3.memory_protected_context import ProtectedMemoryContextCompiler  # noqa: E402
from app.agent3.memory_protected_reader import ProtectedMemoryReader  # noqa: E402
from app.agent3.memory_protection import (  # noqa: E402
    MemoryProtectionCodec,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


if os.name != "nt":
    print("SKIP: protected local-context DPAPI fixture requires Windows")
    raise SystemExit(0)

PRIVATE = "T033-DPAPI-CONTEXT-PRIVATE-17ad5a21"
SOURCE = "T033-DPAPI-CONTEXT-SOURCE-28be6b32"
SECRET = "T033-DPAPI-CONTEXT-SECRET-39cf7c43"
checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


with tempfile.TemporaryDirectory(prefix="kaliv-t033-dpapi-context-") as raw:
    database = Path(raw) / "memory.db"
    store = MemoryStore(str(database))
    try:
        private_id = store.create(
            subject="Anders",
            predicate="dpapi_local_context",
            value=PRIVATE,
            sensitivity="private",
            source_ref=SOURCE,
        ).id
        secret_id = store.create(
            subject="Anders",
            predicate="dpapi_secret_context",
            value=SECRET,
            sensitivity="secret",
        ).id
    finally:
        store.close()

    summary = MemoryProtectionMigrator(
        database,
        MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
    ).migrate()
    check("real DPAPI context fixture migration completes", summary.complete)

    with ProtectedMemoryReader(
        database,
        MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
    ) as reader:
        result = ProtectedMemoryContextCompiler(reader).compile(
            subjects=["Anders"],
            target=ContextTarget.LOCAL,
            max_chars=4_000,
            max_records=10,
        )

    rendered_receipt = json.dumps(result.receipt(), ensure_ascii=False, sort_keys=True)
    check(
        "same Windows user can compile the private value locally",
        private_id in result.context.included_ids and PRIVATE in result.context.text,
    )
    check(
        "real DPAPI local context excludes secret and source provenance",
        secret_id not in result.context.included_ids
        and SECRET not in result.context.text
        and SOURCE not in result.context.text,
    )
    check(
        "real DPAPI context receipt contains no protected plaintext",
        PRIVATE not in rendered_receipt
        and SECRET not in rendered_receipt
        and SOURCE not in rendered_receipt
        and result.receipt()["production_activation"] is False,
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 WINDOWS DPAPI LOCAL CONTEXT: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
