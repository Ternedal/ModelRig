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

# Memory 4.0 W02-A: consolidation plans only; hardened W01 confirmed output is a
# verbatim statement, not a model-authored semantic fact that may replace another.
consolidator = MemoryConsolidator()
existing_verbatim = store.create(
    subject=hardened.subject,
    predicate=hardened.predicate,
    value=hardened.value,
    kind=hardened.kind,
    sensitivity=hardened.sensitivity,
    source_type=hardened.source_type,
    source_ref=hardened.source_ref,
    confidence=hardened.confidence,
)
exact_plan = consolidator.plan([hardened], [existing_verbatim])
check(
    exact_plan.actions[0].decision == "dedupe"
    and exact_plan.actions[0].existing_id == existing_verbatim.id
    and exact_plan.receipt.dedupe_count == 1
    and exact_plan.receipt.sent_to_store is False,
    "W02 exact confirmed verbatim replay dedupes without writing",
)

second_turn = CompletedMemoryTurn(
    user_text="I work in Copenhagen",
    assistant_text="Noted.",
    source_ref="conversation:second-verbatim",
)


async def second_full_turn_extract(_turn):
    row = semantic_trap_row(evidence=second_turn.user_text)
    row["value"] = "Copenhagen"
    return extraction_document(row)


second_hardened = asyncio.run(
    MemoryCandidateExtractor(extract=second_full_turn_extract).extract(second_turn)
)[0]
separate_statement = consolidator.plan(
    [second_hardened],
    [existing_verbatim],
)
check(
    separate_statement.actions[0].decision == "create"
    and separate_statement.actions[0].existing_id is None,
    "W02 never treats different confirmed verbatim statements as stale versions of one semantic fact",
)

legacy_pending_same = store.create(
    subject=hardened.subject,
    predicate=hardened.predicate,
    value=hardened.value,
    kind="note",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:legacy-pending-verbatim",
)
promotion = consolidator.plan([hardened], [legacy_pending_same])
check(
    promotion.actions[0].decision == "supersede"
    and promotion.actions[0].existing_id == legacy_pending_same.id
    and promotion.actions[0].reason == "normalize_exact_value_to_confirmed_verbatim",
    "W02 may version the exact same value from pending legacy form to hardened confirmed verbatim form",
)

semantic_confirmed = store.create(
    subject="anders",
    predicate="favorite_city",
    value="Odense",
    kind="preference",
    sensitivity="private",
    source_type="user_explicit",
)
pending_semantic = consolidator.plan([partial], [semantic_confirmed])
check(
    pending_semantic.actions[0].decision == "create"
    and pending_semantic.actions[0].existing_id is None,
    "W02 pending model semantics cannot supersede a confirmed structured fact",
)

semantic_pending_exact = store.create(
    subject=partial.subject,
    predicate=partial.predicate,
    value=partial.value,
    kind=partial.kind,
    sensitivity="private",
    source_type="inferred",
    source_ref="run:semantic-pending",
)
pending_exact = consolidator.plan([partial], [semantic_pending_exact])
check(
    pending_exact.actions[0].decision == "dedupe"
    and pending_exact.actions[0].existing_id == semantic_pending_exact.id,
    "W02 exact pending semantics dedupe without gaining authority",
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
    consolidator.plan([forged_confirmed], [])
    forged_rejected = False
except MemoryConsolidationError:
    forged_rejected = True
check(
    forged_rejected,
    "W02 rejects confirmed candidates that bypass hardened W01 verbatim normalization",
)

secret_candidate = MemoryCandidate(
    subject="anders",
    predicate="secret_note",
    value="top-secret",
    kind="note",
    sensitivity="secret",
    source_type="user_explicit",
    source_ref="conversation:secret-candidate",
    confidence=0.9,
    review_status="pending",
    evidence="top-secret",
)
secret_plan = consolidator.plan([secret_candidate], [])
check(
    secret_plan.actions[0].decision == "skip"
    and secret_plan.actions[0].reason == "secret_candidate",
    "W02 skips secret candidates before consolidation",
)

multi_verbatim = store.create(
    subject="user",
    predicate="verbatim_user_statement",
    value="A different exact user statement",
    kind="note",
    sensitivity="private",
    source_type="user_explicit",
)
check(
    consolidator.plan([second_hardened], [existing_verbatim, multi_verbatim]).actions[0].decision
    == "create",
    "W02 allows multiple independent confirmed verbatim statements under the generic hardened key",
)

structured_conflict_a = store.create(
    subject="w02",
    predicate="structured_conflict",
    value="a",
    sensitivity="private",
    source_type="user_explicit",
)
structured_conflict_b = store.create(
    subject="w02",
    predicate="structured_conflict",
    value="b",
    sensitivity="private",
    source_type="user_explicit",
)
structured_pending = MemoryCandidate(
    subject="w02",
    predicate="structured_conflict",
    value="c",
    kind="fact",
    sensitivity="private",
    source_type="inferred",
    source_ref="run:structured-conflict",
    confidence=0.5,
    review_status="pending",
    evidence="",
)
try:
    consolidator.plan(
        [structured_pending],
        [structured_conflict_a, structured_conflict_b],
    )
    ambiguous_rejected = False
except MemoryConsolidationError:
    ambiguous_rejected = True
check(
    ambiguous_rejected,
    "W02 fails closed on ambiguous confirmed structured state",
)

try:
    consolidator.plan([hardened] * (MAX_CONSOLIDATION_CANDIDATES + 1), [])
    oversized_rejected = False
except MemoryConsolidationError:
    oversized_rejected = True
check(oversized_rejected, "W02 hard-bounds candidate iterator consumption")

try:
    consolidator.plan([hardened], [secret])
    secret_snapshot_rejected = False
except MemoryConsolidationError:
    secret_snapshot_rejected = True
check(secret_snapshot_rejected, "W02 refuses secret records in its trusted snapshot")

receipt_text = json.dumps(exact_plan.to_dict(), ensure_ascii=False)
check(
    hardened.value not in receipt_text and hardened.source_ref not in receipt_text,
    "W02 serialized plan receipt does not leak private candidate value or source_ref",
)

store.close()
reopened = MemoryStore(path)
check(reopened.get(inferred.id).review_status == "confirmed", "memory state persists across reopen")
reopened.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
