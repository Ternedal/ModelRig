#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import time

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation import (
    apply_legacy_persistence,
    plan_legacy_consolidation,
    plan_protected_consolidation,
)
from app.agent3.memory_protected_reader import MemoryReadAccess
from app.memory import MemoryCandidate


checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def pending(predicate: str, value: str) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate=predicate,
        value=value,
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        source_ref="turn:w02b-edge",
        confidence=0.7,
        review_status="pending",
        evidence="",
    )


def secret() -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="api_key",
        value="sk-edge-secret-memory4",
        kind="note",
        sensitivity="secret",
        source_type="user_explicit",
        source_ref="turn:w02b-secret-edge",
        confidence=1.0,
        review_status="pending",
        evidence="sk-edge-secret-memory4",
    )


class CountingProtectedReader:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def list(self, *, access, **kwargs):
        self.calls.append((access, kwargs))
        return []


reader = CountingProtectedReader()
neutral_secret, persistence_secret = plan_protected_consolidation(reader, [secret()])
check(
    "secret neutral action remains skip",
    neutral_secret.actions[0].decision == "skip"
    and persistence_secret.decisions[0].outcome == "skip",
)
check(
    "secret skip performs no persistence slot read or extra decryption pass",
    len(reader.calls) == 1
    and reader.calls[0][0] is MemoryReadAccess.LOCAL_MANAGEMENT
    and reader.calls[0][1].get("include_secret") is False,
)

path = os.path.join(tempfile.mkdtemp(prefix="memory4-w02b-expiry-"), "memory.db")
store = MemoryStore(path)
try:
    candidate = pending("expired_exact", "same value")
    expired = store.create(
        **candidate.store_fields(),
        expires_at=time.time() - 10,
    )
    neutral, persistence = plan_legacy_consolidation(store, [candidate])
    decision = persistence.decisions[0]
    check(
        "neutral planner excludes expired durable state and proposes create",
        neutral.actions[0].decision == "create",
    )
    check(
        "persistence revalidation refuses to reuse an expired exact row",
        decision.outcome == "review"
        and decision.reason == "exact_value_requires_review"
        and decision.existing_id == expired.id,
    )
    before = store.list(
        subject="user",
        predicate="expired_exact",
        include_expired=True,
    )
    applied = apply_legacy_persistence(store, decision)
    after = store.list(
        subject="user",
        predicate="expired_exact",
        include_expired=True,
    )
    check(
        "expired exact review handoff performs no mutation",
        applied.memory_id is None
        and [row.id for row in before] == [expired.id]
        and [row.id for row in after] == [expired.id],
    )
finally:
    store.close()


failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MEMORY 4 W02-B PERSISTENCE EDGES: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
