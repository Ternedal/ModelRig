from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from app.memory.completed_turn_persistence import (
    MemoryTurnPersistenceError,
    MemoryTurnPersistenceOrchestrator,
    TURN_PERSISTENCE_RECEIPT_SCHEMA,
    W02_WRITE_RECEIPT_SCHEMA,
)
from app.memory.consolidation import ConsolidationPlan, ConsolidationReceipt, MemoryConsolidator
from app.memory.extraction import CompletedMemoryTurn, MemoryCandidate


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def canonical(turn: CompletedMemoryTurn) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=turn.user_text,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=turn.source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=turn.user_text,
    )


def pending(turn: CompletedMemoryTurn, *, source_type: str = "inferred", sensitivity: str = "private") -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="favorite_city",
        value="København",
        kind="preference",
        sensitivity=sensitivity,
        source_type=source_type,
        source_ref=turn.source_ref,
        confidence=0.7,
        review_status="pending",
        evidence="København" if source_type == "user_explicit" else "",
    )


@dataclass(frozen=True)
class FakeWriteReceipt:
    schema: str = W02_WRITE_RECEIPT_SCHEMA
    considered_count: int = 1
    created_ids: tuple[str, ...] = ("memory-1",)
    superseded_ids: tuple[str, ...] = ()
    superseding_ids: tuple[str, ...] = ()
    deduped_ids: tuple[str, ...] = ()
    skipped_count: int = 0
    replayed: bool = False
    sent_to_store: bool = True


turn = CompletedMemoryTurn(
    user_text="Jeg bor i København",
    assistant_text="Det har jeg noteret.",
    source_ref="turn:w03a-1",
)

calls = {"extract": 0, "plan": 0, "apply": 0}


async def extract_success(value):
    calls["extract"] += 1
    return (canonical(value),)


def plan_success(candidates):
    calls["plan"] += 1
    return MemoryConsolidator().plan(candidates, ())


def apply_success(plan):
    calls["apply"] += 1
    return FakeWriteReceipt(considered_count=len(plan.actions))


receipt = asyncio.run(
    MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_success,
        prepare_plan=plan_success,
        apply_plan=apply_success,
    ).persist(turn)
)
check(
    receipt.schema == TURN_PERSISTENCE_RECEIPT_SCHEMA
    and receipt.extracted_count == 1
    and receipt.eligible_count == 1
    and receipt.deferred_count == 0
    and receipt.sent_to_store is True
    and receipt.write_receipt is not None
    and receipt.write_receipt.created_ids == ("memory-1",)
    and calls == {"extract": 1, "plan": 1, "apply": 1},
    "canonical whole-turn W01 statement reaches injected W02 callbacks",
)
serialized = repr(receipt.to_dict())
check(
    turn.user_text not in serialized
    and turn.assistant_text not in serialized
    and turn.source_ref not in serialized,
    "W03-A receipt exposes counts/ids but no turn text or source provenance",
)
check(
    "app.memory.local_extraction" not in sys.modules,
    "shared W03-A import does not eagerly import local Ollama extraction adapter",
)


async def extract_deferred(value):
    return (
        pending(value, source_type="inferred"),
        pending(value, source_type="imported"),
        pending(value, source_type="tool_observation"),
        pending(value, source_type="user_explicit"),
        pending(value, source_type="inferred", sensitivity="secret"),
    )


def must_not_plan(_candidates):
    raise AssertionError("deferred candidates must not reach W02 planning")


def must_not_apply(_plan):
    raise AssertionError("deferred candidates must not reach W02 storage")


deferred = asyncio.run(
    MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_deferred,
        prepare_plan=must_not_plan,
        apply_plan=must_not_apply,
    ).persist(turn)
)
check(
    deferred.extracted_count == 5
    and deferred.eligible_count == 0
    and deferred.deferred_count == 5
    and deferred.sent_to_store is False
    and deferred.write_receipt is None,
    "pending/inferred/imported/tool/secret proposals are deferred before W02",
)


async def extract_empty(_value):
    return ()


empty = asyncio.run(
    MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_empty,
        prepare_plan=must_not_plan,
        apply_plan=must_not_apply,
    ).persist(turn)
)
check(
    empty.extracted_count == empty.eligible_count == empty.deferred_count == 0
    and empty.write_receipt is None,
    "empty extraction performs no plan or storage callback",
)


def expect_error(name, coroutine_factory, contains=None):
    try:
        asyncio.run(coroutine_factory())
    except MemoryTurnPersistenceError as exc:
        check(contains is None or contains in str(exc), name)
        return exc
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)
    return None


async def extract_list(value):
    return [canonical(value)]


expect_error(
    "non-tuple W01 callback output fails closed",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_list,
        prepare_plan=plan_success,
        apply_plan=apply_success,
    ).persist(turn),
    "candidate tuple",
)


async def extract_wrong_source(value):
    item = canonical(value)
    return (
        MemoryCandidate(
            subject=item.subject,
            predicate=item.predicate,
            value=item.value,
            kind=item.kind,
            sensitivity=item.sensitivity,
            source_type=item.source_type,
            source_ref="turn:forged",
            confidence=item.confidence,
            review_status=item.review_status,
            evidence=item.evidence,
        ),
    )


expect_error(
    "candidate provenance must bind exact completed-turn source_ref",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_wrong_source,
        prepare_plan=plan_success,
        apply_plan=apply_success,
    ).persist(turn),
    "source_ref",
)


async def extract_canonical(value):
    return (canonical(value),)


def forged_plan(candidates):
    return ConsolidationPlan(
        actions=(),
        receipt=ConsolidationReceipt(0, 0, 0, 0, 0, (), False),
    )


expect_error(
    "plan callback must bind every eligible candidate",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_canonical,
        prepare_plan=forged_plan,
        apply_plan=apply_success,
    ).persist(turn),
    "bind every eligible candidate",
)


def bad_receipt(plan):
    return FakeWriteReceipt(considered_count=len(plan.actions) + 1)


expect_error(
    "write receipt count mismatch fails closed",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_canonical,
        prepare_plan=plan_success,
        apply_plan=bad_receipt,
    ).persist(turn),
    "candidate count",
)


def failing_apply(_plan):
    raise RuntimeError("storage exploded with private detail")


error = expect_error(
    "storage failure is surfaced as bounded W03-A failure",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_canonical,
        prepare_plan=plan_success,
        apply_plan=failing_apply,
    ).persist(turn),
    "durable apply failed",
)
check(
    error is not None
    and isinstance(error.__cause__, RuntimeError)
    and "private detail" not in str(error),
    "storage diagnostics remain in the exception cause, not the public W03-A message",
)


async def extract_too_many(value):
    rows = []
    for index in range(17):
        rows.append(
            MemoryCandidate(
                subject="user",
                predicate=f"pending_{index}",
                value=f"value-{index}",
                kind="fact",
                sensitivity="private",
                source_type="inferred",
                source_ref=value.source_ref,
                confidence=0.5,
                review_status="pending",
                evidence="",
            )
        )
    return tuple(rows)


expect_error(
    "W03-A inherits W02 candidate hard bound before storage callbacks",
    lambda: MemoryTurnPersistenceOrchestrator(
        extract_candidates=extract_too_many,
        prepare_plan=must_not_plan,
        apply_plan=must_not_apply,
    ).persist(turn),
    "outside W02 bounds",
)


print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
