#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from app.memory import (  # noqa: E402
    COMPLETED_TURN_PERSISTENCE_SCHEMA,
    CompletedMemoryTurn,
    CompletedTurnMemoryOrchestrator,
    MemoryCandidate,
    MemoryConsolidator,
    MemoryOrchestrationError,
)
from source_code import code_of  # noqa: E402

WRITE_SCHEMA = "kaliv-memory-consolidation-write-receipt/v1"
passed = failed = 0


def check(condition: object, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(name: str, fn, error_type) -> None:
    try:
        fn()
    except error_type:
        check(True, name)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)


@dataclass(frozen=True)
class FakeWriteReceipt:
    schema: str
    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool = True


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


def created_receipt(count: int = 1) -> FakeWriteReceipt:
    return FakeWriteReceipt(
        schema=WRITE_SCHEMA,
        considered_count=count,
        created_ids=tuple(f"memory-w03-{index}" for index in range(count)),
        superseded_ids=(),
        superseding_ids=(),
        deduped_ids=(),
        skipped_count=0,
        replayed=False,
    )


# Canonical success: one W01-confirmed verbatim statement reaches W02, and the
# outer receipt contains only bounded counts + durable ids.
turn = CompletedMemoryTurn(
    user_text="W03-CANONICAL-USER-TEXT-4f91",
    assistant_text="Acknowledged.",
    source_ref="conversation:W03-SOURCE-4f91",
)
candidate = canonical(turn)
seen: dict[str, object] = {}


async def extract_success(received: CompletedMemoryTurn):
    seen["turn"] = received
    return (candidate,)


def plan_success(candidates):
    seen["planned"] = candidates
    return MemoryConsolidator().plan(candidates, ())


def apply_success(plan):
    seen["applied"] = plan
    return created_receipt()


receipt = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract_success,
        prepare_plan=plan_success,
        apply_plan=apply_success,
    ).persist(turn)
)
check(receipt.schema == COMPLETED_TURN_PERSISTENCE_SCHEMA, "W03 receipt schema")
check(
    (receipt.extracted_count, receipt.eligible_count, receipt.deferred_count)
    == (1, 1, 0),
    "canonical W01 candidate is the only auto-persistable class",
)
check(seen.get("planned") == (candidate,), "W02 plan sees exact eligible tuple")
check(
    receipt.write_receipt is not None
    and receipt.write_receipt.created_ids == ("memory-w03-0",),
    "W03 projects the value-free W02 durable receipt",
)
serialized = json.dumps(receipt.to_dict(), sort_keys=True)
check(turn.user_text not in serialized, "W03 receipt does not leak candidate value")
check(turn.source_ref not in serialized, "W03 receipt does not leak source_ref")
check(candidate.evidence not in serialized, "W03 receipt does not leak evidence")


# All non-canonical W01 classes are deferred before either injected W02 callback.
deferred_turn = CompletedMemoryTurn(
    user_text="I live in Copenhagen and prefer local models.",
    assistant_text="Okay.",
    source_ref="conversation:W03-DEFER-91ba",
)
deferred = (
    MemoryCandidate(
        subject="user",
        predicate="home_city",
        value="Copenhagen",
        kind="fact",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=deferred_turn.source_ref,
        confidence=0.95,
        review_status="pending",
        evidence="I live in Copenhagen",
    ),
    MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value="prefer local models",
        kind="note",
        sensitivity="secret",
        source_type="user_explicit",
        source_ref=deferred_turn.source_ref,
        confidence=0.8,
        review_status="pending",
        evidence="I live in Copenhagen and prefer local models.",
    ),
    MemoryCandidate(
        subject="user",
        predicate="inferred_preference",
        value="local-first",
        kind="preference",
        sensitivity="private",
        source_type="inferred",
        source_ref=deferred_turn.source_ref,
        confidence=0.7,
        review_status="pending",
        evidence="",
    ),
    MemoryCandidate(
        subject="user",
        predicate="imported_note",
        value="imported-value-91ba",
        kind="note",
        sensitivity="private",
        source_type="imported",
        source_ref=deferred_turn.source_ref,
        confidence=0.8,
        review_status="pending",
        evidence="",
    ),
    MemoryCandidate(
        subject="user",
        predicate="tool_note",
        value="tool-value-91ba",
        kind="note",
        sensitivity="private",
        source_type="tool_observation",
        source_ref=deferred_turn.source_ref,
        confidence=0.9,
        review_status="pending",
        evidence="",
    ),
)
calls = {"plan": 0, "apply": 0}


async def extract_deferred(_turn):
    return deferred


def must_not_plan(_candidates):
    calls["plan"] += 1
    raise AssertionError("deferred candidates reached W02 planning")


def must_not_apply(_plan):
    calls["apply"] += 1
    raise AssertionError("deferred candidates reached W02 storage")


deferred_receipt = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract_deferred,
        prepare_plan=must_not_plan,
        apply_plan=must_not_apply,
    ).persist(deferred_turn)
)
check(
    (
        deferred_receipt.extracted_count,
        deferred_receipt.eligible_count,
        deferred_receipt.deferred_count,
    )
    == (5, 0, 5),
    "pending/secret/inferred/imported/tool candidates are all deferred",
)
check(calls == {"plan": 0, "apply": 0}, "no eligible candidate means no W02 callback")
check(
    deferred_receipt.write_receipt is None,
    "all-deferred batch returns deterministic no-write receipt",
)
check(
    deferred_receipt.to_dict()
    == {
        "schema": COMPLETED_TURN_PERSISTENCE_SCHEMA,
        "extracted_count": 5,
        "eligible_count": 0,
        "deferred_count": 5,
        "write_receipt": None,
    },
    "all-deferred W03 receipt is value-free and deterministic",
)


# Mixed batch: W02 receives only the canonical candidate, never the deferred row.
mixed_turn = CompletedMemoryTurn(
    user_text="W03-MIXED-CANONICAL-20d7",
    assistant_text="Okay.",
    source_ref="conversation:W03-MIXED-20d7",
)
mixed_canonical = canonical(mixed_turn)
mixed_pending = MemoryCandidate(
    subject="user",
    predicate="model_semantic_guess",
    value="guess-20d7",
    kind="fact",
    sensitivity="private",
    source_type="inferred",
    source_ref=mixed_turn.source_ref,
    confidence=0.6,
    review_status="pending",
    evidence="",
)
mixed_seen = {}


async def extract_mixed(_turn):
    return (mixed_pending, mixed_canonical)


def plan_mixed(candidates):
    mixed_seen["candidates"] = candidates
    return MemoryConsolidator().plan(candidates, ())


mixed_receipt = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract_mixed,
        prepare_plan=plan_mixed,
        apply_plan=lambda _plan: created_receipt(),
    ).persist(mixed_turn)
)
check(
    mixed_seen.get("candidates") == (mixed_canonical,),
    "mixed batch strips deferred semantics before W02",
)
check(
    (mixed_receipt.extracted_count, mixed_receipt.eligible_count, mixed_receipt.deferred_count)
    == (2, 1, 1),
    "mixed W03 counts remain exact",
)


# Empty extraction is a deterministic no-op and never touches W02 callbacks.
empty_calls = {"plan": 0, "apply": 0}


async def extract_empty(_turn):
    return ()


def empty_plan(_candidates):
    empty_calls["plan"] += 1
    raise AssertionError("empty extraction reached planner")


def empty_apply(_plan):
    empty_calls["apply"] += 1
    raise AssertionError("empty extraction reached storage")


empty_receipt = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract_empty,
        prepare_plan=empty_plan,
        apply_plan=empty_apply,
    ).persist(turn)
)
check(
    empty_receipt.to_dict()
    == {
        "schema": COMPLETED_TURN_PERSISTENCE_SCHEMA,
        "extracted_count": 0,
        "eligible_count": 0,
        "deferred_count": 0,
        "write_receipt": None,
    },
    "empty extraction returns deterministic zero receipt",
)
check(empty_calls == {"plan": 0, "apply": 0}, "empty extraction performs no W02 call")


# Callback output contracts fail closed.
async def extract_list(_turn):
    return [candidate]


expect_error(
    "non-tuple W01 callback output fails closed",
    lambda: asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=extract_list,
            prepare_plan=plan_success,
            apply_plan=apply_success,
        ).persist(turn)
    ),
    MemoryOrchestrationError,
)


async def extract_one(_turn):
    return (candidate,)


expect_error(
    "malformed W02 plan callback result fails closed",
    lambda: asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=extract_one,
            prepare_plan=lambda _candidates: object(),
            apply_plan=apply_success,
        ).persist(turn)
    ),
    MemoryOrchestrationError,
)


def malformed_receipt(_plan):
    return FakeWriteReceipt(
        schema=WRITE_SCHEMA,
        considered_count=2,
        created_ids=("memory-w03-malformed",),
        superseded_ids=(),
        superseding_ids=(),
        deduped_ids=(),
        skipped_count=0,
        replayed=False,
    )


expect_error(
    "malformed W02 write receipt binding fails closed",
    lambda: asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=extract_one,
            prepare_plan=lambda candidates: MemoryConsolidator().plan(candidates, ()),
            apply_plan=malformed_receipt,
        ).persist(turn)
    ),
    MemoryOrchestrationError,
)


# The extraction callback must really be async; a sync fake cannot bypass W01.
def sync_extract(_turn):
    return (candidate,)


expect_error(
    "synchronous W01 extraction callback fails closed",
    lambda: asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=sync_extract,
            prepare_plan=plan_success,
            apply_plan=apply_success,
        ).persist(turn)
    ),
    MemoryOrchestrationError,
)


# Storage exceptions are not converted into a success-like receipt.
class StorageBoom(RuntimeError):
    pass


def storage_boom(_plan):
    raise StorageBoom("synthetic W03 storage failure")


expect_error(
    "W02 storage failure propagates",
    lambda: asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=extract_one,
            prepare_plan=lambda candidates: MemoryConsolidator().plan(candidates, ()),
            apply_plan=storage_boom,
        ).persist(turn)
    ),
    StorageBoom,
)


# Static dependency check: shared W03 core must not import Agent 3 storage or the
# local Ollama extraction adapter. Those dependencies belong in later adapters.
orchestration_source = code_of(ROOT / "worker" / "app" / "memory" / "orchestration.py")
check("app.agent3" not in orchestration_source, "W03 shared core has no Agent 3 import")
check(
    "local_extraction" not in orchestration_source,
    "W03 shared core does not import the local Ollama adapter",
)

print(f"\n===== W03-A ORCHESTRATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
