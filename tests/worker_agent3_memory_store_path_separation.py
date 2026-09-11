#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_consolidation import (  # noqa: E402
    MemoryConsolidationApplyError,
    apply_legacy_consolidation_decision,
    apply_protected_consolidation_decision,
    plan_legacy_consolidation,
    plan_protected_consolidation,
)
from app.agent3.memory_protected_reader import MemoryReadAccess  # noqa: E402
from app.agent3.memory_protected_writer import MemoryWriteAccess  # noqa: E402
from app.agent3.memory_surface import mount_memory_surface  # noqa: E402
from app.memory import (  # noqa: E402
    ACTION_CREATE,
    ACTION_REUSE,
    ACTION_REVIEW,
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_CONSOLIDATION_RECORDS,
    MemoryCandidate,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from app.memory.extraction import (  # noqa: E402
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
)

checks: list[tuple[str, bool]] = []
SIGNING_MATERIAL = hashlib.sha256(
    b"t033-store-path-separation-fixture"
).hexdigest()


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


@contextmanager
def environment(**values: str):
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class MustNotBeConstructed:
    def __init__(self) -> None:
        raise AssertionError("provider must not be constructed before path validation")


with tempfile.TemporaryDirectory(prefix="kaliv-t033-path-separation-") as raw:
    shared = Path(raw) / "shared.db"
    with environment(
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_API_SECRET=SIGNING_MATERIAL,
        KALIV_AGENT3_MEMORY_GRANT_DB=str(shared),
    ):
        try:
            mount_memory_surface(
                FastAPI(),
                memory_path=shared,
                grant_db_path=shared,
                protected_provider_factory=MustNotBeConstructed,
            )
        except RuntimeError as exc:
            check(
                "shared memory and replay-ledger path fails closed",
                "separate" in str(exc),
            )
        else:
            check("shared memory and replay-ledger path fails closed", False)
        check(
            "shared path failure happens before database/provider creation",
            not shared.exists(),
        )


# Memory 4.0 W02 (#1198) is deliberately colocated in an existing memory suite so
# CURRENT_STATE's generated top-level test inventory does not drift. W02 must
# preserve the stricter W01 confirmed-authority shape from #1201/#1202.
def confirmed_statement(text: str, *, source_ref: str = "conversation:w02") -> MemoryCandidate:
    return MemoryCandidate(
        subject=VERBATIM_USER_SUBJECT,
        predicate=VERBATIM_USER_PREDICATE,
        value=text,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=text,
    )


def pending_candidate(
    *,
    subject: str = "anders",
    predicate: str = "city",
    value: str = "Copenhagen",
    kind: str = "fact",
    sensitivity: str = "private",
    source_type: str = "inferred",
) -> MemoryCandidate:
    return MemoryCandidate(
        subject=subject,
        predicate=predicate,
        value=value,
        kind=kind,
        sensitivity=sensitivity,
        source_type=source_type,
        source_ref="conversation:w02-pending",
        confidence=0.7,
        review_status="pending",
        evidence="",
    )


with tempfile.TemporaryDirectory(prefix="kaliv-memory4-w02-") as raw:
    store = MemoryStore(str(Path(raw) / "memory.db"))

    first = confirmed_statement("I live in Copenhagen")
    duplicate_plan = plan_legacy_consolidation(store, [first, first])
    check(
        "W02 exact confirmed duplicate cluster produces one create",
        duplicate_plan.candidate_count == 2
        and len(duplicate_plan.decisions) == 1
        and duplicate_plan.decisions[0].action == ACTION_CREATE,
    )
    created = apply_legacy_consolidation_decision(store, duplicate_plan.decisions[0])
    check(
        "W02 first verbatim statement is persisted once",
        created.action == ACTION_CREATE
        and len(
            store.list(
                subject=VERBATIM_USER_SUBJECT,
                predicate=VERBATIM_USER_PREDICATE,
                include_secret=True,
            )
        )
        == 1,
    )

    reuse_plan = plan_legacy_consolidation(store, [first])
    check(
        "W02 exact durable verbatim duplicate is reused",
        reuse_plan.decisions[0].action == ACTION_REUSE,
    )
    reused = apply_legacy_consolidation_decision(store, reuse_plan.decisions[0])
    check(
        "W02 reuse creates no repeated durable row",
        reused.memory_id == created.memory_id
        and len(
            store.list(
                subject=VERBATIM_USER_SUBJECT,
                predicate=VERBATIM_USER_PREDICATE,
                include_secret=True,
            )
        )
        == 1,
    )

    second = confirmed_statement("My workstation has 96 GB RAM")
    second_plan = plan_legacy_consolidation(store, [second])
    check(
        "W02 distinct confirmed verbatim statements are independent notes",
        second_plan.decisions[0].action == ACTION_CREATE
        and second_plan.decisions[0].existing_id is None,
    )
    apply_legacy_consolidation_decision(store, second_plan.decisions[0])
    check(
        "W02 distinct verbatim note does not supersede the first statement",
        len(
            store.list(
                subject=VERBATIM_USER_SUBJECT,
                predicate=VERBATIM_USER_PREDICATE,
                include_secret=True,
            )
        )
        == 2,
    )

    forged_confirmed = MemoryCandidate(
        subject="anders",
        predicate="favorite_city",
        value="Copenhagen",
        kind="preference",
        sensitivity="private",
        source_type="user_explicit",
        source_ref="conversation:forged",
        confidence=1.0,
        review_status="confirmed",
        evidence="Copenhagen",
    )
    try:
        MemoryConsolidator().plan([forged_confirmed], [])
    except MemoryConsolidationError:
        check("W02 rejects handcrafted structured confirmed authority", True)
    else:
        check("W02 rejects handcrafted structured confirmed authority", False)

    pending_a = pending_candidate(predicate="pending-conflict", value="A")
    pending_b = pending_candidate(predicate="pending-conflict", value="B")
    conflict = plan_legacy_consolidation(store, [pending_a, pending_b])
    check(
        "W02 conflicting pending structured values fail closed to review",
        len(conflict.decisions) == 2
        and all(item.action == ACTION_REVIEW for item in conflict.decisions),
    )

    durable_city = store.create(
        subject="anders",
        predicate="city",
        value="Aarhus",
        kind="fact",
        sensitivity="private",
        source_type="user_explicit",
        review_status="confirmed",
    )
    stale = plan_legacy_consolidation(
        store,
        [pending_candidate(predicate="city", value="Copenhagen")],
    ).decisions[0]
    check(
        "W02 stale structured fact becomes an exact review handoff",
        stale.action == ACTION_REVIEW
        and stale.reason == "stale_fact_requires_review"
        and stale.existing_id == durable_city.id
        and stale.expected_updated_at == durable_city.updated_at,
    )
    reviewed = apply_legacy_consolidation_decision(store, stale)
    check(
        "W02 review handoff does not mutate durable history",
        reviewed.action == ACTION_REVIEW
        and store.get(durable_city.id).value == "Aarhus"
        and store.get(durable_city.id).lifecycle_status == "active",
    )

    kind_guard = store.create(
        subject="anders",
        predicate="kind-guard",
        value="same",
        kind="preference",
        sensitivity="private",
        source_type="user_explicit",
    )
    kind_decision = plan_legacy_consolidation(
        store,
        [pending_candidate(predicate="kind-guard", value="same", kind="fact")],
    ).decisions[0]
    check(
        "W02 kind mismatch cannot be silently reused",
        kind_decision.action == ACTION_REVIEW
        and kind_decision.reason == "kind_mismatch"
        and kind_decision.existing_id == kind_guard.id,
    )

    public_guard = store.create(
        subject="anders",
        predicate="sensitivity-guard",
        value="same",
        kind="fact",
        sensitivity="public",
        source_type="user_explicit",
    )
    sensitivity_decision = plan_legacy_consolidation(
        store,
        [pending_candidate(predicate="sensitivity-guard", value="same")],
    ).decisions[0]
    check(
        "W02 refuses under-classified durable sensitivity",
        sensitivity_decision.action == ACTION_REVIEW
        and sensitivity_decision.reason == "sensitivity_underclassified"
        and sensitivity_decision.existing_id == public_guard.id,
    )

    pending_row = store.create(
        subject="anders",
        predicate="reuse-race",
        value="same",
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        review_status="pending",
    )
    reuse_race = plan_legacy_consolidation(
        store,
        [pending_candidate(predicate="reuse-race", value="same")],
    ).decisions[0]
    check("W02 pending exact duplicate can initially reuse", reuse_race.action == ACTION_REUSE)
    store.confirm(pending_row.id)
    try:
        apply_legacy_consolidation_decision(store, reuse_race)
    except MemoryConsolidationApplyError:
        check("W02 stale reuse optimistic token fails closed", True)
    else:
        check("W02 stale reuse optimistic token fails closed", False)

    create_race_candidate = pending_candidate(predicate="create-race", value="planned")
    create_race = plan_legacy_consolidation(store, [create_race_candidate]).decisions[0]
    store.create(
        subject="anders",
        predicate="create-race",
        value="concurrent",
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        review_status="pending",
    )
    try:
        apply_legacy_consolidation_decision(store, create_race)
    except MemoryConsolidationApplyError:
        check("W02 stale create plan fails closed", True)
    else:
        check("W02 stale create plan fails closed", False)

    secret_candidate = pending_candidate(
        predicate="secret-guard",
        value="sk-example-secret-12345678",
        sensitivity="secret",
        source_type="user_explicit",
    )
    store.create(
        subject="anders",
        predicate="secret-guard",
        value="old",
        kind="fact",
        sensitivity="private",
        source_type="user_explicit",
    )
    secret_decision = plan_legacy_consolidation(store, [secret_candidate]).decisions[0]
    check(
        "W02 secret candidate remains non-replacing review state",
        secret_candidate.review_status == "pending"
        and secret_decision.action == ACTION_REVIEW,
    )

    try:
        MemoryConsolidator().plan(
            [
                pending_candidate(predicate=f"candidate-cap-{index}", value=str(index))
                for index in range(MAX_CONSOLIDATION_CANDIDATES + 1)
            ],
            [],
        )
    except MemoryConsolidationError:
        check("W02 candidate batch is hard-capped", True)
    else:
        check("W02 candidate batch is hard-capped", False)

    probe = store.get(durable_city.id)
    try:
        MemoryConsolidator().plan(
            [pending_candidate(predicate="record-cap", value="x")],
            [probe] * (MAX_CONSOLIDATION_RECORDS + 1),
        )
    except MemoryConsolidationError:
        check("W02 existing record batch is hard-capped", True)
    else:
        check("W02 existing record batch is hard-capped", False)

    store.close()


class FakeProtectedReader:
    def __init__(self):
        self.accesses: list[object] = []
        self.rows: list[object] = []

    def list(self, *, access, **_kwargs):
        self.accesses.append(access)
        return list(self.rows)


class FakeProtectedWriter:
    def __init__(self):
        self.calls: list[tuple[object, dict[str, object]]] = []

    def create(self, *, access, **fields):
        self.calls.append((access, fields))

        class Created:
            id = "protected-w02-created"

        return Created()


protected_reader = FakeProtectedReader()
protected_writer = FakeProtectedWriter()
protected_candidate = confirmed_statement("My local memory note")
protected_plan = plan_protected_consolidation(
    protected_reader,  # type: ignore[arg-type]
    [protected_candidate],
)
check(
    "W02 protected planning uses local-management read authority",
    protected_plan.decisions[0].action == ACTION_CREATE
    and protected_reader.accesses
    and all(access is MemoryReadAccess.LOCAL_MANAGEMENT for access in protected_reader.accesses),
)
protected_applied = apply_protected_consolidation_decision(
    protected_reader,  # type: ignore[arg-type]
    protected_writer,  # type: ignore[arg-type]
    protected_plan.decisions[0],
)
check(
    "W02 protected create uses existing local-management writer authority",
    protected_applied.action == ACTION_CREATE
    and len(protected_writer.calls) == 1
    and protected_writer.calls[0][0] is MemoryWriteAccess.LOCAL_MANAGEMENT,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 STORE PATH SEPARATION + MEMORY4 W02: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
