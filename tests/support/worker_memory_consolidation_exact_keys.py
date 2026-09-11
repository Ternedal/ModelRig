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

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
