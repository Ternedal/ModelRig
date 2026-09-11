from __future__ import annotations

import asyncio

from app.memory import (
    CONSOLIDATION_WRITE_RECEIPT_SCHEMA,
    CompletedMemoryTurn,
    CompletedTurnMemoryPersistence,
    CompletedTurnPersistenceError,
    MemoryCandidate,
    MemoryConsolidator,
)


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(name, awaitable, contains=None):
    try:
        asyncio.run(awaitable)
    except CompletedTurnPersistenceError as exc:
        check(contains is None or contains in str(exc), name)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)


def canonical(value="Jeg bruger ModelRig lokalt.", source_ref="conversation:w03-a"):
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


def pending_semantic(
    *,
    source_type="inferred",
    sensitivity="private",
    source_ref="conversation:w03-pending",
):
    return MemoryCandidate(
        subject="modelrig",
        predicate="likely_gpu",
        value="RTX 3060",
        kind="fact",
        sensitivity=sensitivity,
        source_type=source_type,
        source_ref=source_ref,
        confidence=0.8,
        review_status="pending",
        evidence="",
    )


def write_receipt(
    *,
    considered=1,
    created=("mem-created",),
    superseded=(),
    superseding=(),
    deduped=(),
    skipped=0,
    replayed=False,
    sent_to_store=True,
):
    return {
        "schema": CONSOLIDATION_WRITE_RECEIPT_SCHEMA,
        "considered_count": considered,
        "created_count": len(created),
        "superseded_count": len(superseded),
        "deduped_count": len(deduped),
        "skipped_count": skipped,
        "created_ids": list(created),
        "superseded_ids": list(superseded),
        "superseding_ids": list(superseding),
        "deduped_ids": list(deduped),
        "replayed": replayed,
        "sent_to_store": sent_to_store,
    }


turn = CompletedMemoryTurn(
    user_text="Jeg bruger ModelRig lokalt.",
    assistant_text="Noteret.",
    source_ref="conversation:w03-a",
)

# Canonical W01 confirmed output is the only auto-persistable shape.
canonical_candidate = canonical()
prepare_calls = []
apply_calls = []


async def extract_canonical(_turn):
    return (canonical_candidate,)


def prepare_canonical(candidates):
    prepare_calls.append(candidates)
    return MemoryConsolidator().plan(candidates, ())


def apply_canonical(plan):
    apply_calls.append(plan)
    return write_receipt()


receipt = asyncio.run(
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_canonical,
        prepare_plan=prepare_canonical,
        apply_plan=apply_canonical,
    ).persist(turn)
)
check(
    receipt.extracted_count == 1
    and receipt.eligible_count == 1
    and receipt.deferred_count == 0
    and receipt.sent_to_store
    and receipt.write_receipt is not None
    and receipt.write_receipt.created_ids == ("mem-created",)
    and prepare_calls == [(canonical_candidate,)]
    and len(apply_calls) == 1,
    "W03-A forwards only canonical confirmed W01 output into W02 planning/write callbacks",
)
check(
    "value" not in receipt.to_dict()
    and "evidence" not in receipt.to_dict()
    and "source_ref" not in receipt.to_dict(),
    "W03-A receipt projection does not expose memory values evidence or source provenance",
)

# Pending/secret/model-semantic proposals are deferred before either storage callback.
secret_pending = pending_semantic(
    sensitivity="secret",
    source_ref="conversation:w03-secret",
)
user_pending = MemoryCandidate(
    subject="modelrig",
    predicate="gpu",
    value="RTX 3060",
    kind="fact",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:w03-user-pending",
    confidence=0.8,
    review_status="pending",
    evidence="Jeg bruger RTX 3060.",
)
no_write_calls = []


async def extract_deferred(_turn):
    return (
        pending_semantic(),
        pending_semantic(source_type="tool_observation", source_ref="conversation:w03-tool"),
        secret_pending,
        user_pending,
    )


def must_not_prepare(_candidates):
    no_write_calls.append("prepare")
    raise AssertionError("deferred-only W03-A batch must not prepare a W02 plan")


def must_not_apply(_plan):
    no_write_calls.append("apply")
    raise AssertionError("deferred-only W03-A batch must not reach storage")


deferred = asyncio.run(
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_deferred,
        prepare_plan=must_not_prepare,
        apply_plan=must_not_apply,
    ).persist(turn)
)
check(
    deferred.extracted_count == 4
    and deferred.eligible_count == 0
    and deferred.deferred_count == 4
    and not deferred.sent_to_store
    and deferred.write_receipt is None
    and no_write_calls == [],
    "W03-A defers pending secret inferred tool and partial semantic candidates before storage",
)

# A mixed batch forwards only the canonical confirmed candidate.
mixed_seen = []


async def extract_mixed(_turn):
    return (pending_semantic(), canonical_candidate)


def prepare_mixed(candidates):
    mixed_seen.extend(candidates)
    return MemoryConsolidator().plan(candidates, ())


mixed = asyncio.run(
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_mixed,
        prepare_plan=prepare_mixed,
        apply_plan=lambda _plan: write_receipt(),
    ).persist(turn)
)
check(
    mixed.extracted_count == 2
    and mixed.eligible_count == 1
    and mixed.deferred_count == 1
    and mixed_seen == [canonical_candidate],
    "W03-A strips deferred candidates before W02-A plan preparation",
)

# A fabricated confirmed semantic MemoryCandidate is rejected even if injected
# directly after W01; it cannot piggyback on W03-A to storage.
forged_confirmed = MemoryCandidate(
    subject="modelrig",
    predicate="favorite_gpu",
    value="RTX 3060",
    kind="preference",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:w03-forged",
    confidence=1.0,
    review_status="confirmed",
    evidence="RTX 3060",
)


async def extract_forged(_turn):
    return (forged_confirmed,)


expect_error(
    "W03-A revalidates and rejects fabricated confirmed semantic authority before planning",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_forged,
        prepare_plan=lambda candidates: MemoryConsolidator().plan(candidates, ()),
        apply_plan=lambda _plan: write_receipt(),
    ).persist(turn),
    "W01/W02 contract",
)

# The plan callback cannot add/replace eligible candidates.
extra_candidate = canonical(
    "Jeg bruger også en anden model.",
    "conversation:w03-extra",
)


def prepare_injected(_candidates):
    return MemoryConsolidator().plan((canonical_candidate, extra_candidate), ())


expect_error(
    "W03-A rejects a W02-A plan that injects an extra candidate",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_canonical,
        prepare_plan=prepare_injected,
        apply_plan=lambda _plan: write_receipt(),
    ).persist(turn),
    "candidate count",
)

# W02-B receipt binding is validated again before W03-A reports persistence.
expect_error(
    "W03-A rejects a write receipt that does not claim durable storage",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_canonical,
        prepare_plan=prepare_canonical,
        apply_plan=lambda _plan: write_receipt(sent_to_store=False),
    ).persist(turn),
    "authority flags",
)
expect_error(
    "W03-A rejects a write receipt with mismatched action accounting",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_canonical,
        prepare_plan=prepare_canonical,
        apply_plan=lambda _plan: write_receipt(considered=2),
    ).persist(turn),
    "considered_count",
)


def failing_write(_plan):
    raise RuntimeError("synthetic storage failure")


expect_error(
    "W03-A surfaces storage failure as a fail-closed persistence error",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_canonical,
        prepare_plan=prepare_canonical,
        apply_plan=failing_write,
    ).persist(turn),
    "durable write failed",
)

# W03-A independently enforces the W01 candidate-count hard bound even if a
# custom extractor bypasses MemoryCandidateExtractor.
async def extract_too_many(_turn):
    return tuple(
        canonical(
            f"W03 bounded statement {index}",
            f"conversation:w03-bounded-{index}",
        )
        for index in range(17)
    )


expect_error(
    "W03-A rejects extractor output beyond the W01 16-candidate bound",
    CompletedTurnMemoryPersistence(
        extract_candidates=extract_too_many,
        prepare_plan=prepare_canonical,
        apply_plan=apply_canonical,
    ).persist(turn),
    "candidate bound",
)

# Extraction must remain async; W03-A must not reinterpret a synchronous model
# or caller result as trusted W01 output.
def sync_extract(_turn):
    return (canonical_candidate,)


expect_error(
    "W03-A requires an async extraction callback",
    CompletedTurnMemoryPersistence(
        extract_candidates=sync_extract,
        prepare_plan=prepare_canonical,
        apply_plan=apply_canonical,
    ).persist(turn),
    "must be async",
)

print(f"\n===== W03-A COMPLETED TURN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
