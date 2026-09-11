from __future__ import annotations

from app.agent3.memory import MemoryStore
from app.agent3.memory_consolidation_writer import apply_legacy_consolidation_plan
from app.memory import MemoryCandidate, MemoryConsolidator


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def candidate(subject: str, predicate: str, source_ref: str) -> MemoryCandidate:
    return MemoryCandidate(
        subject=subject,
        predicate=predicate,
        value="same-value",
        kind="fact",
        sensitivity="private",
        source_type="inferred",
        source_ref=source_ref,
        confidence=0.8,
        review_status="pending",
        evidence="",
    )


def confirmed_statement(value: str, source_ref: str) -> MemoryCandidate:
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


upper = candidate("Anders", "Project_Status", "conversation:upper")
lower = candidate("anders", "project_status", "conversation:lower")

batch = MemoryConsolidator().plan([upper, lower], [])
check(
    [action.decision for action in batch.actions] == ["create", "create"],
    "W02 does not grant case-normalization merge authority to model-authored keys",
)

store = MemoryStore(":memory:")
lower_row = store.create(**lower.store_fields())
upper_plan = MemoryConsolidator().plan([upper], [])
receipt = apply_legacy_consolidation_plan(store, upper_plan)
check(
    receipt.created_count == 1,
    "W02-B exact-key lookup stays aligned with W02-A planning",
)
active = store.list(include_secret=True, limit=10)
check(
    {(row.subject, row.predicate, row.id) for row in active}
    == {
        (lower.subject, lower.predicate, lower_row.id),
        (upper.subject, upper.predicate, receipt.created_ids[0]),
    },
    "case-distinct storage keys remain independent durable records",
)
store.close()

# Canonical verbatim memory is a statement log, not a singleton semantic slot.
# A large history of different statements therefore must not consume the entire
# W02-A snapshot budget for one new independent statement.
log_store = MemoryStore(":memory:")
for index in range(140):
    historical = confirmed_statement(
        f"Historical statement {index}",
        f"conversation:historical-{index}",
    )
    log_store.create(**historical.store_fields())
new_statement = confirmed_statement(
    "I prefer bounded exact statement lookup",
    "conversation:new-verbatim",
)
new_plan = MemoryConsolidator().plan([new_statement], [])
new_receipt = apply_legacy_consolidation_plan(log_store, new_plan)
check(
    new_receipt.created_count == 1
    and log_store.get(new_receipt.created_ids[0]).value == new_statement.value,
    "W02-B does not let 128+ unrelated verbatim statements exhaust a new statement write",
)
log_store.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
