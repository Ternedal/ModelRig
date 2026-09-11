#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation import (
    MemoryConsolidationApplyError,
    PersistenceDecision,
    apply_legacy_persistence,
)
from app.memory import MemoryCandidate


checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_apply_error(label: str, fn) -> None:
    try:
        fn()
    except MemoryConsolidationApplyError:
        check(label, True)
    except Exception:
        check(label, False)
    else:
        check(label, False)


def secret_candidate() -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="api_key",
        value="sk-secret-memory4-authority",
        kind="note",
        sensitivity="secret",
        source_type="user_explicit",
        source_ref="turn:secret-authority-test",
        confidence=1.0,
        review_status="pending",
        evidence="sk-secret-memory4-authority",
    )


path = os.path.join(
    tempfile.mkdtemp(prefix="memory4-w02b-secret-authority-"),
    "memory.db",
)
store = MemoryStore(path)
try:
    candidate = secret_candidate()

    forged_create = PersistenceDecision(
        outcome="create",
        candidate=candidate,
        existing_id=None,
        expected_updated_at=None,
        reason="forged_create",
    )
    expect_apply_error(
        "forged secret create cannot bypass W02 prepare authority",
        lambda: apply_legacy_persistence(store, forged_create),
    )
    check(
        "forged secret create writes no durable row",
        not store.list(
            subject=candidate.subject,
            predicate=candidate.predicate,
            include_secret=True,
        ),
    )

    existing = store.create(**candidate.store_fields())
    forged_reuse = PersistenceDecision(
        outcome="reuse",
        candidate=candidate,
        existing_id=existing.id,
        expected_updated_at=existing.updated_at,
        reason="forged_reuse",
    )
    expect_apply_error(
        "forged secret reuse cannot gain automatic persistence authority",
        lambda: apply_legacy_persistence(store, forged_reuse),
    )
    check(
        "forged secret reuse leaves durable secret unchanged",
        store.get(existing.id).value == candidate.value
        and store.get(existing.id).lifecycle_status == "active",
    )
finally:
    store.close()


failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MEMORY 4 W02-B PERSISTENCE AUTHORITY: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
