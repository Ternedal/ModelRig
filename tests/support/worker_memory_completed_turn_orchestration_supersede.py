#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from app.memory import (  # noqa: E402
    CompletedMemoryTurn,
    CompletedTurnMemoryOrchestrator,
    ConsolidationAction,
    ConsolidationPlan,
    ConsolidationReceipt,
    MemoryCandidate,
    MemoryOrchestrationError,
)

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


turn = CompletedMemoryTurn(
    user_text="W03A-SUPERSEDE-CANONICAL-6cb9",
    assistant_text="Acknowledged.",
    source_ref="conversation:W03A-SUPERSEDE-6cb9",
)
candidate = MemoryCandidate(
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
old_id = "memory-pending-6cb9"
replacement_id = "memory-confirmed-6cb9"
plan = ConsolidationPlan(
    actions=(
        ConsolidationAction(
            candidate=candidate,
            decision="supersede",
            existing_id=old_id,
            reason="exact_verbatim_authority_promotion",
        ),
    ),
    receipt=ConsolidationReceipt(
        considered_count=1,
        create_count=0,
        dedupe_count=0,
        supersede_count=1,
        skip_count=0,
        touched_existing_ids=(old_id,),
        sent_to_store=False,
    ),
)


async def extract(_turn):
    return (candidate,)


def prepare(_candidates):
    return plan


def apply_supersede(_plan):
    return FakeWriteReceipt(
        schema=WRITE_SCHEMA,
        considered_count=1,
        created_ids=(replacement_id,),
        superseded_ids=(old_id,),
        superseding_ids=(replacement_id,),
        deduped_ids=(),
        skipped_count=0,
        replayed=False,
    )


receipt = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract,
        prepare_plan=prepare,
        apply_plan=apply_supersede,
    ).persist(turn)
)
check(
    receipt.write_receipt is not None
    and receipt.write_receipt.created_ids == (replacement_id,)
    and receipt.write_receipt.superseded_ids == (old_id,)
    and receipt.write_receipt.superseding_ids == (replacement_id,),
    "fresh W02 supersede receipt accepts replacement as a created id",
)


def apply_replay(_plan):
    return FakeWriteReceipt(
        schema=WRITE_SCHEMA,
        considered_count=1,
        created_ids=(),
        superseded_ids=(),
        superseding_ids=(),
        deduped_ids=(replacement_id,),
        skipped_count=0,
        replayed=True,
    )


replay = asyncio.run(
    CompletedTurnMemoryOrchestrator(
        extract_candidates=extract,
        prepare_plan=prepare,
        apply_plan=apply_replay,
    ).persist(turn)
)
check(
    replay.write_receipt is not None
    and replay.write_receipt.replayed
    and replay.write_receipt.deduped_ids == (replacement_id,),
    "replayed W02 supersede is represented as a dedupe outcome",
)


def malformed_supersede(_plan):
    return FakeWriteReceipt(
        schema=WRITE_SCHEMA,
        considered_count=1,
        created_ids=(),
        superseded_ids=(old_id,),
        superseding_ids=(replacement_id,),
        deduped_ids=(),
        skipped_count=0,
        replayed=False,
    )


try:
    asyncio.run(
        CompletedTurnMemoryOrchestrator(
            extract_candidates=extract,
            prepare_plan=prepare,
            apply_plan=malformed_supersede,
        ).persist(turn)
    )
except MemoryOrchestrationError:
    check(True, "superseding id missing from created ids fails closed")
else:
    check(False, "superseding id missing from created ids fails closed")

print(f"\n===== W03-A SUPERSEDE RECEIPT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
