from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time

from app.agent3.memory import MemoryNotFound, MemoryStore, MemoryStoreError
from app.memory import (
    MAX_CONSOLIDATION_CANDIDATES,
    CompletedMemoryTurn,
    MEMORY_CANDIDATE_SCHEMA,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryConsolidationError,
    MemoryConsolidator,
)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_consolidation_error(name, fn, contains=None):
    try:
        fn()
    except MemoryConsolidationError as exc:
        check(contains is None or contains in str(exc), name)
    except Exception:
        check(False, name)
    else:
        check(False, name)


path = os.path.join(tempfile.mkdtemp(prefix="agent3-memory-"), "memory.db")
store = MemoryStore(path)

explicit = store.create(
    subject="anders",
    predicate="foretrækker_mad",
    value="ingen fisk",
    kind="preference",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:123",
)
check(explicit.review_status == "confirmed", "explicit user memory is confirmed by default")
check(explicit.source_ref == "conversation:123", "explicit memory preserves provenance")
check(store.get(explicit.id).value == "ingen fisk", "created memory survives a database read")

inferred = store.create(
    subject="anders",
    predicate="foretrækker_model",
    value="qwen",
    kind="preference",
    sensitivity="operational",
    source_type="inferred",
    confidence=0.65,
    source_ref="run:abc",
)
check(inferred.review_status == "pending", "inferred memory is pending by default")
check(inferred.id not in {m.id for m in store.context_records()}, "pending memory is excluded from context")
confirmed = store.confirm(inferred.id)
check(confirmed.review_status == "confirmed", "pending memory can be explicitly confirmed")
check(confirmed.id in {m.id for m in store.context_records()}, "confirmed memory enters local context")

corrected = store.correct(
    explicit.id,
    value="ingen fisk eller sushi",
    source_ref="conversation:456",
)
old = store.get(explicit.id)
check(old.lifecycle_status == "superseded", "correction supersedes the old version")
check(corrected.supersedes_id == explicit.id, "new version points to the version it replaced")
check(corrected.value == "ingen fisk eller sushi", "corrected value is stored separately")
history = store.history("anders", "foretrækker_mad")
check([m.lifecycle_status for m in history] == ["superseded", "active"], "version history is preserved")
check([m.id for m in store.list(subject="anders", predicate="foretrækker_mad")] == [corrected.id], "normal lookup returns only active version")

secret = store.create(
    subject="anders",
    predicate="hemmelig_nøgle",
    value="top-secret",
    sensitivity="secret",
    source_type="user_explicit",
)
check(secret.id not in {m.id for m in store.context_records()}, "secret memory is excluded from normal context")
check(secret.id not in {m.id for m in store.search("top-secret")}, "secret memory is excluded from normal search")
check(secret.id in {m.id for m in store.context_records(include_secret=True)}, "secret context requires explicit opt-in")

private_context = store.context_records(include_private=False)
check(all(m.sensitivity not in {"private", "secret"} for m in private_context), "private context can be disabled")

expired = store.create(
    subject="anders",
    predicate="midlertidig_status",
    value="travl",
    kind="note",
    sensitivity="operational",
    source_type="user_explicit",
    expires_at=time.time() - 1,
)
check(expired.id not in {m.id for m in store.list()}, "expired memory is excluded from normal listing")
check(expired.id in {m.id for m in store.list(include_expired=True)}, "expired memory remains inspectable")

literal = store.create(
    subject="test",
    predicate="wildcard",
    value="100%_literal",
    sensitivity="operational",
)
check(literal.id in {m.id for m in store.search("%_")}, "search treats SQL wildcard characters literally")

try:
    store.create(subject="x", predicate="bad", value="x", confidence=1.5)
    bad_confidence = False
except MemoryStoreError:
    bad_confidence = True
check(bad_confidence, "invalid confidence is rejected")

pending_reject = store.create(
    subject="anders",
    predicate="usikker",
    value="måske",
    source_type="tool_observation",
)
rejected = store.reject(pending_reject.id)
check(rejected.review_status == "rejected", "pending observation can be rejected")
check(rejected.id not in {m.id for m in store.context_records()}, "rejected memory never enters context")

deleted = store.delete(corrected.id)
check(deleted.lifecycle_status == "deleted", "delete creates a tombstone")
check(deleted.value == "" and deleted.source_ref is None, "delete erases value and source reference")
try:
    store.get(corrected.id)
    hidden_deleted = False
except MemoryNotFound:
    hidden_deleted = True
check(hidden_deleted, "deleted memory is hidden from normal get")
check(store.get(corrected.id, include_deleted=True).lifecycle_status == "deleted", "tombstone remains inspectable")
check(corrected.id not in {m.id for m in store.context_records(include_secret=True)}, "deleted memory never enters context")

# Budget must be respected even when the first candidate is larger than the cap.
large = store.create(
    subject="budget",
    predicate="long",
    value="x" * 200,
    sensitivity="operational",
)
small_budget = store.context_records(subjects=["budget"], max_chars=20)
check(not small_budget, "context compiler respects max_chars for the first record")

# Memory 4.0 W01 authority hardening (#1201): literal evidence proves only the
# exact user statement, never model-authored semantics layered on top of it.
def extraction_document(*candidates):
    return json.dumps(
        {"schema": MEMORY_CANDIDATE_SCHEMA, "candidates": list(candidates)},
        ensure_ascii=False,
    )


def semantic_trap_row(*, evidence="I live in Copenhagen"):
    return {
        "subject": "anders",
        "predicate": "favorite_city",
        "value": "Copenhagen",
        "kind": "preference",
        "sensitivity": "public",
        "source_type": "user_explicit",
        "confidence": 0.99,
        "evidence": evidence,
    }


authority_turn = CompletedMemoryTurn(
    user_text="I live in Copenhagen",
    assistant_text="Noted.",
    source_ref="conversation:authority-hardening",
)


async def semantic_trap_extract(_turn):
    return extraction_document(semantic_trap_row())


hardened = asyncio.run(
    MemoryCandidateExtractor(extract=semantic_trap_extract).extract(authority_turn)
)[0]
check(
    hardened.review_status == "confirmed",
    "full literal user-turn evidence may still gain confirmed review status",
)
check(
    hardened.subject == "user"
    and hardened.predicate == "verbatim_user_statement"
    and hardened.value == authority_turn.user_text
    and hardened.kind == "note"
    and hardened.sensitivity == "private"
    and hardened.confidence == 1.0,
    "confirmed W01 memory discards model-authored semantic relation and classification",
)
check(
    hardened.source_ref == "conversation:authority-hardening",
    "authority hardening preserves caller-owned provenance",
)


async def partial_evidence_extract(_turn):
    return extraction_document(semantic_trap_row(evidence="Copenhagen"))


partial = asyncio.run(
    MemoryCandidateExtractor(extract=partial_evidence_extract).extract(authority_turn)
)[0]
check(
    partial.review_status == "pending"
    and partial.predicate == "favorite_city"
    and partial.value == "Copenhagen",
    "entity-only literal evidence cannot auto-confirm a model-generated relation",
)


async def padded_evidence_extract(_turn):
    return extraction_document(semantic_trap_row(evidence=" I live in Copenhagen "))


padded = asyncio.run(
    MemoryCandidateExtractor(extract=padded_evidence_extract).extract(authority_turn)
)[0]
check(
    padded.review_status == "pending",
    "extractor whitespace normalization cannot manufacture confirmed authority",
)

# Memory 4.0 W02-A: storage-neutral consolidation must preserve the stricter W01
# authority boundary. A neutral verbatim statement is a statement log entry, not
# a semantic singleton slot that may overwrite another statement.
consolidator = MemoryConsolidator()

new_statement_plan = consolidator.plan([hardened], [])
check(
    len(new_statement_plan.actions) == 1
    and new_statement_plan.actions[0].decision == "create"
    and new_statement_plan.actions[0].reason == "new_confirmed_verbatim_statement"
    and new_statement_plan.receipt.sent_to_store is False,
    "W02-A plans a new canonical confirmed statement without touching storage",
)

existing_same_statement = store.create(
    subject="user",
    predicate="verbatim_user_statement",
    value="I live in Copenhagen",
    kind="note",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:older-same-statement",
    confidence=1.0,
    review_status="confirmed",
)
exact_statement_plan = consolidator.plan([hardened], [existing_same_statement])
check(
    exact_statement_plan.actions[0].decision == "dedupe"
    and exact_statement_plan.actions[0].existing_id == existing_same_statement.id,
    "W02-A exact confirmed verbatim replay dedupes deterministically",
)

existing_other_statement_a = store.create(
    subject="user",
    predicate="verbatim_user_statement",
    value="I live in Aarhus",
    kind="note",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:other-a",
    confidence=1.0,
    review_status="confirmed",
)
existing_other_statement_b = store.create(
    subject="user",
    predicate="verbatim_user_statement",
    value="I work in Odense",
    kind="note",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:other-b",
    confidence=1.0,
    review_status="confirmed",
)
distinct_statement_plan = consolidator.plan(
    [hardened],
    [existing_other_statement_b, existing_other_statement_a],
)
check(
    distinct_statement_plan.actions[0].decision == "create"
    and distinct_statement_plan.receipt.supersede_count == 0,
    "W02-A never treats different verbatim user turns as stale versions of one fact",
)

pending_semantic = partial
pending_semantic_plan = consolidator.plan([pending_semantic], [])
check(
    pending_semantic_plan.actions[0].decision == "create"
    and pending_semantic_plan.actions[0].reason == "new_pending_candidate",
    "W02-A may plan storage of a structured pending proposal for later review",
)

existing_semantic_confirmed = store.create(
    subject="anders",
    predicate="favorite_city",
    value="Copenhagen",
    kind="preference",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:reviewed-city",
    confidence=1.0,
    review_status="confirmed",
)
semantic_exact_plan = consolidator.plan(
    [pending_semantic],
    [existing_semantic_confirmed],
)
check(
    semantic_exact_plan.actions[0].decision == "dedupe"
    and semantic_exact_plan.actions[0].existing_id == existing_semantic_confirmed.id,
    "W02-A pending proposal can dedupe against an exact already-reviewed durable fact",
)

forged_confirmed_semantic = MemoryCandidate(
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
expect_consolidation_error(
    "W02-A rejects a hand-built confirmed semantic candidate even when it claims user_explicit provenance",
    lambda: consolidator.plan([forged_confirmed_semantic], []),
    "verbatim authority shape",
)

pending_verbatim = store.create(
    subject="user",
    predicate="verbatim_user_statement",
    value="I live in Copenhagen",
    kind="note",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:pending-verbatim",
    confidence=0.4,
    review_status="pending",
)
promotion_plan = consolidator.plan([hardened], [pending_verbatim])
check(
    promotion_plan.actions[0].decision == "supersede"
    and promotion_plan.actions[0].existing_id == pending_verbatim.id
    and promotion_plan.actions[0].reason == "exact_verbatim_authority_promotion",
    "W02-A permits only exact pending-to-confirmed verbatim authority promotion",
)

secret_candidate = MemoryCandidate(
    subject="user",
    predicate="token",
    value="hidden-token",
    kind="note",
    sensitivity="secret",
    source_type="inferred",
    source_ref="conversation:secret-candidate",
    confidence=0.8,
    review_status="pending",
    evidence="",
)
secret_plan = consolidator.plan([secret_candidate], [])
check(
    secret_plan.actions[0].decision == "skip"
    and secret_plan.actions[0].reason == "secret_candidate",
    "W02-A keeps secret candidates outside consolidation writes",
)

less_restrictive_existing = store.create(
    subject="anders",
    predicate="favorite_city",
    value="Copenhagen",
    kind="preference",
    sensitivity="public",
    source_type="user_explicit",
    source_ref="conversation:old-public-city",
    confidence=1.0,
    review_status="confirmed",
)
expect_consolidation_error(
    "W02-A refuses exact dedupe that would silently declassify a private W01 candidate",
    lambda: consolidator.plan([pending_semantic], [less_restrictive_existing]),
    "less restrictive",
)

pending_duplicate_a = MemoryCandidate(
    subject="modelrig",
    predicate="likely_model",
    value="qwen",
    kind="fact",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:z-source",
    confidence=0.5,
    review_status="pending",
    evidence="",
)
pending_duplicate_b = MemoryCandidate(
    subject="modelrig",
    predicate="likely_model",
    value="qwen",
    kind="fact",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:a-source",
    confidence=0.5,
    review_status="pending",
    evidence="",
)
duplicate_plan = consolidator.plan([pending_duplicate_a, pending_duplicate_b], [])
check(
    [action.decision for action in duplicate_plan.actions] == ["create", "skip"]
    and duplicate_plan.actions[0].candidate.source_ref == "run:a-source",
    "W02-A batch dedupe is order-independent and deterministic by canonical sort",
)

ambiguous_semantic_a = store.create(
    subject="w02",
    predicate="ambiguous",
    value="a",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:ambiguous-a",
    review_status="confirmed",
)
ambiguous_semantic_b = store.create(
    subject="w02",
    predicate="ambiguous",
    value="b",
    sensitivity="private",
    source_type="user_explicit",
    source_ref="conversation:ambiguous-b",
    review_status="confirmed",
)
expect_consolidation_error(
    "W02-A fails closed when semantic durable state already has multiple active confirmed values",
    lambda: consolidator.plan(
        [pending_duplicate_a],
        [ambiguous_semantic_b, ambiguous_semantic_a],
    ),
    "ambiguous confirmed semantic state",
)

expect_consolidation_error(
    "W02-A hard-bounds candidate batch size before planning work",
    lambda: consolidator.plan(
        [pending_duplicate_a] * (MAX_CONSOLIDATION_CANDIDATES + 1),
        [],
    ),
    "exceeds",
)
expect_consolidation_error(
    "W02-A rejects secret durable records from its snapshot",
    lambda: consolidator.plan([pending_duplicate_a], [secret]),
    "secret memory",
)

public_plan = consolidator.plan([secret_candidate], [])
projection = public_plan.to_dict()
check(
    "hidden-token" not in json.dumps(projection)
    and "conversation:secret-candidate" not in json.dumps(projection),
    "W02-A public plan projection omits candidate values evidence and source_ref",
)

store.close()
reopened = MemoryStore(path)
check(reopened.get(inferred.id).review_status == "confirmed", "memory state persists across reopen")
reopened.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
