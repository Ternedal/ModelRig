#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation import (
    apply_legacy_persistence,
    plan_legacy_consolidation,
)
from app.memory import MemoryCandidate


checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def pending(
    predicate: str,
    value: str,
    *,
    kind: str = "fact",
    confidence: float = 0.7,
) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate=predicate,
        value=value,
        kind=kind,
        sensitivity="private",
        source_type="inferred",
        source_ref="turn:w02b-batch",
        confidence=confidence,
        review_status="pending",
        evidence="",
    )


path = os.path.join(tempfile.mkdtemp(prefix="memory4-w02b-batch-"), "memory.db")
store = MemoryStore(path)
try:
    value_a = pending("project_state", "alpha")
    value_b = pending("project_state", "beta")
    neutral_values, persistence_values = plan_legacy_consolidation(
        store,
        [value_b, value_a],
    )
    check(
        "W02-A independently sees both empty-slot structured candidates as creates",
        len(neutral_values.actions) == 2
        and all(action.decision == "create" for action in neutral_values.actions),
    )
    check(
        "W02-B converts same-slot value disagreement to review before any write",
        persistence_values.mutation_count == 0
        and persistence_values.requires_review
        and all(
            decision.outcome == "review"
            and decision.reason == "conflicting_structured_batch"
            for decision in persistence_values.decisions
        ),
    )
    for decision in persistence_values.decisions:
        apply_legacy_persistence(store, decision)
    check(
        "same-slot value conflict remains order-independent and writes nothing",
        not store.list(subject="user", predicate="project_state"),
    )

    meta_a = pending("metadata_conflict", "same", kind="fact", confidence=0.7)
    meta_b = pending(
        "metadata_conflict",
        "same",
        kind="preference",
        confidence=0.9,
    )
    _, persistence_meta = plan_legacy_consolidation(store, [meta_a, meta_b])
    check(
        "same-slot metadata disagreement cannot produce an automatic mutation",
        persistence_meta.mutation_count == 0
        and persistence_meta.requires_review
        and all(
            decision.outcome in {"review", "skip"}
            for decision in persistence_meta.decisions
        )
        and any(
            decision.outcome == "review"
            and decision.reason == "conflicting_structured_batch"
            for decision in persistence_meta.decisions
        ),
    )
    for decision in persistence_meta.decisions:
        apply_legacy_persistence(store, decision)
    check(
        "same-slot metadata conflict writes no durable row",
        not store.list(subject="user", predicate="metadata_conflict"),
    )
finally:
    store.close()


failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MEMORY 4 W02-B PERSISTENCE BATCH: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
