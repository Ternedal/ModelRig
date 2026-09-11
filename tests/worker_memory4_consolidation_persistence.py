#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation import (
    MemoryConsolidationApplyError,
    apply_legacy_persistence,
    apply_protected_persistence,
    plan_legacy_consolidation,
    plan_protected_consolidation,
)
from app.agent3.memory_protected_reader import MemoryReadAccess
from app.agent3.memory_protected_writer import MemoryWriteAccess
from app.memory import MemoryCandidate


checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def verbatim(value: str, *, source_ref: str = "turn:w02b") -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=value,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=value,
    )


def pending(
    predicate: str,
    value: str,
    *,
    kind: str = "fact",
    source_type: str = "inferred",
    source_ref: str = "turn:w02b",
) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate=predicate,
        value=value,
        kind=kind,
        sensitivity="private",
        source_type=source_type,
        source_ref=source_ref,
        confidence=0.7,
        review_status="pending",
        evidence="",
    )


def expect_apply_error(label: str, fn) -> None:
    try:
        fn()
    except MemoryConsolidationApplyError:
        check(label, True)
    except Exception:
        check(label, False)
    else:
        check(label, False)


path = os.path.join(tempfile.mkdtemp(prefix="memory4-w02b-"), "memory.db")
store = MemoryStore(path)
try:
    first = verbatim("Jeg kan ikke lide fisk", source_ref="turn:1")
    second = verbatim("Jeg bruger en RTX 3060", source_ref="turn:2")

    neutral_first, persistence_first = plan_legacy_consolidation(store, [first])
    check(
        "new confirmed verbatim statement prepares a create",
        neutral_first.actions[0].decision == "create"
        and persistence_first.decisions[0].outcome == "create",
    )
    applied_first = apply_legacy_persistence(store, persistence_first.decisions[0])

    neutral_second, persistence_second = plan_legacy_consolidation(store, [second])
    check(
        "different verbatim statement sharing canonical slot remains an independent create",
        neutral_second.actions[0].decision == "create"
        and persistence_second.decisions[0].outcome == "create",
    )
    applied_second = apply_legacy_persistence(store, persistence_second.decisions[0])
    verbatim_rows = store.list(subject="user", predicate="verbatim_user_statement")
    check(
        "independent verbatim statements coexist durably without supersede",
        applied_first.memory_id != applied_second.memory_id
        and {row.value for row in verbatim_rows} == {first.value, second.value}
        and all(row.lifecycle_status == "active" for row in verbatim_rows),
    )

    neutral_replay, persistence_replay = plan_legacy_consolidation(store, [first])
    replay = persistence_replay.decisions[0]
    check(
        "exact replay becomes a bound reuse decision",
        neutral_replay.actions[0].decision == "dedupe"
        and replay.outcome == "reuse"
        and replay.existing_id == applied_first.memory_id
        and replay.expected_updated_at is not None,
    )
    check(
        "reusing exact verbatim statement does not create a third row",
        apply_legacy_persistence(store, replay).memory_id == applied_first.memory_id
        and len(store.list(subject="user", predicate="verbatim_user_statement")) == 2,
    )

    reviewed = store.create(
        subject="user",
        predicate="reviewed_city",
        value="Berlin",
        kind="preference",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="review:local",
    )
    structured = pending("reviewed_city", "Copenhagen", kind="preference")
    neutral_structured, persistence_structured = plan_legacy_consolidation(
        store, [structured]
    )
    handoff = persistence_structured.decisions[0]
    check(
        "structured contradiction is upgraded from neutral create to exact review handoff",
        neutral_structured.actions[0].decision == "create"
        and handoff.outcome == "review"
        and handoff.reason == "contradicts_reviewed_fact"
        and handoff.existing_id == reviewed.id
        and handoff.expected_updated_at == reviewed.updated_at,
    )
    before = store.get(reviewed.id)
    applied_review = apply_legacy_persistence(store, handoff)
    after = store.get(reviewed.id)
    check(
        "review handoff performs no automatic correction or supersede",
        applied_review.memory_id is None
        and before.id == after.id
        and before.value == after.value
        and before.updated_at == after.updated_at,
    )

    pending_verbatim = store.create(
        subject="user",
        predicate="verbatim_user_statement",
        value="Jeg bor i København",
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="turn:old",
        confidence=1.0,
        review_status="pending",
    )
    promoted = verbatim("Jeg bor i København", source_ref="turn:new")
    neutral_promotion, persistence_promotion = plan_legacy_consolidation(
        store, [promoted]
    )
    promotion = persistence_promotion.decisions[0]
    check(
        "neutral exact pending-to-confirmed supersede is converted to explicit review",
        neutral_promotion.actions[0].decision == "supersede"
        and promotion.outcome == "review"
        and promotion.reason == "explicit_local_correction_required"
        and promotion.existing_id == pending_verbatim.id
        and promotion.expected_updated_at == pending_verbatim.updated_at,
    )
    apply_legacy_persistence(store, promotion)
    check(
        "W02 review of authority promotion leaves pending durable row untouched",
        store.get(pending_verbatim.id).review_status == "pending"
        and store.get(pending_verbatim.id).lifecycle_status == "active",
    )

    new_pending = pending("project_state", "active", kind="project")
    _, new_pending_plan = plan_legacy_consolidation(store, [new_pending])
    pending_create = new_pending_plan.decisions[0]
    check(
        "new structured pending candidate may be created for later review",
        pending_create.outcome == "create",
    )
    pending_created = apply_legacy_persistence(store, pending_create)
    _, pending_replay_plan = plan_legacy_consolidation(store, [new_pending])
    check(
        "exact pending durable value reuses rather than duplicates",
        pending_replay_plan.decisions[0].outcome == "reuse"
        and apply_legacy_persistence(
            store, pending_replay_plan.decisions[0]
        ).memory_id
        == pending_created.memory_id,
    )

    create_race_candidate = pending("create_race", "planned")
    _, create_race_plan = plan_legacy_consolidation(store, [create_race_candidate])
    create_race = create_race_plan.decisions[0]
    store.create(
        subject="user",
        predicate="create_race",
        value="concurrent",
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        review_status="pending",
    )
    expect_apply_error(
        "structured create is revalidated and refuses a concurrent slot write",
        lambda: apply_legacy_persistence(store, create_race),
    )

    reuse_base = store.create(
        subject="user",
        predicate="reuse_race",
        value="same",
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        review_status="pending",
    )
    _, reuse_race_plan = plan_legacy_consolidation(
        store, [pending("reuse_race", "same")]
    )
    reuse_race = reuse_race_plan.decisions[0]
    store.correct(reuse_base.id, value="changed", source_ref="review:changed")
    expect_apply_error(
        "reuse refuses stale id/update state after concurrent correction",
        lambda: apply_legacy_persistence(store, reuse_race),
    )

    verbatim_race = verbatim("Samtidig verbatim")
    _, verbatim_race_plan = plan_legacy_consolidation(store, [verbatim_race])
    planned_verbatim_create = verbatim_race_plan.decisions[0]
    store.create(**verbatim_race.store_fields())
    expect_apply_error(
        "verbatim create refuses a concurrent exact duplicate but allows other notes",
        lambda: apply_legacy_persistence(store, planned_verbatim_create),
    )
finally:
    store.close()


class FakeProtectedReader:
    def __init__(self):
        self.calls = []

    def list(self, *, access, **kwargs):
        self.calls.append((access, kwargs))
        return []


class FakeProtectedWriter:
    def __init__(self):
        self.calls = []
        self.correct_calls = 0

    def create(self, *, access, **kwargs):
        self.calls.append((access, kwargs))
        return SimpleNamespace(id="protected-created")

    def correct(self, *args, **kwargs):
        self.correct_calls += 1
        raise AssertionError("W02-B must never call protected correct")


reader = FakeProtectedReader()
writer = FakeProtectedWriter()
protected_candidate = pending("protected_project", "active", kind="project")
neutral_protected, persistence_protected = plan_protected_consolidation(
    reader, [protected_candidate]
)
protected_decision = persistence_protected.decisions[0]
protected_applied = apply_protected_persistence(reader, writer, protected_decision)
check(
    "protected W02 create uses exact LOCAL_MANAGEMENT read/write authority",
    neutral_protected.actions[0].decision == "create"
    and protected_decision.outcome == "create"
    and protected_applied.memory_id == "protected-created"
    and reader.calls
    and all(access is MemoryReadAccess.LOCAL_MANAGEMENT for access, _ in reader.calls)
    and writer.calls[0][0] is MemoryWriteAccess.LOCAL_MANAGEMENT,
)
check(
    "protected create preserves pending provenance and never invokes correct",
    writer.calls[0][1]["review_status"] == "pending"
    and writer.calls[0][1]["source_type"] == "inferred"
    and writer.correct_calls == 0,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MEMORY 4 W02-B PERSISTENCE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
