from __future__ import annotations

from dataclasses import replace
import os
import tempfile
import time

from app.agent3.memory import MemoryNotFound, MemoryStore, MemoryStoreError
from app.agent3.memory_consolidation import (
    MemoryConsolidationApplyError,
    apply_legacy_consolidation_decision,
    plan_legacy_consolidation,
)
from app.memory import (
    ACTION_CREATE,
    ACTION_REUSE,
    ACTION_REVIEW,
    ACTION_SUPERSEDE,
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_CONSOLIDATION_RECORDS,
    MemoryCandidate,
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


def w02_candidate(
    *,
    subject="anders",
    predicate="w02_fact",
    value="ny værdi",
    kind="fact",
    sensitivity="private",
    source_type="user_explicit",
    confidence=1.0,
    review_status="confirmed",
    source_ref="conversation:w02",
):
    evidence = value if source_type == "user_explicit" else ""
    return MemoryCandidate(
        subject=subject,
        predicate=predicate,
        value=value,
        kind=kind,
        sensitivity=sensitivity,
        source_type=source_type,
        source_ref=source_ref,
        confidence=confidence,
        review_status=review_status,
        evidence=evidence,
    )


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

store.close()
reopened = MemoryStore(path)
check(reopened.get(inferred.id).review_status == "confirmed", "memory state persists across reopen")
reopened.close()

# Memory 4.0 W02: bounded deterministic consolidation with no model calls.
w02_path = os.path.join(tempfile.mkdtemp(prefix="memory4-w02-"), "memory.db")
w02_store = MemoryStore(w02_path)

candidate = w02_candidate(predicate="new_slot", value="alpha")
plan = plan_legacy_consolidation(w02_store, [candidate, candidate])
check(
    plan.candidate_count == 2
    and len(plan.decisions) == 1
    and plan.decisions[0].action == ACTION_CREATE,
    "W02 clusters exact duplicate candidates into one deterministic create decision",
)
applied = apply_legacy_consolidation_decision(w02_store, plan.decisions[0])
check(
    applied.action == ACTION_CREATE
    and len(w02_store.list(subject="anders", predicate="new_slot")) == 1,
    "W02 exact duplicate cluster creates only one durable row",
)
reuse = plan_legacy_consolidation(w02_store, [candidate])
check(
    len(reuse.decisions) == 1 and reuse.decisions[0].action == ACTION_REUSE,
    "W02 reuses an exact confirmed durable duplicate",
)
reused = apply_legacy_consolidation_decision(w02_store, reuse.decisions[0])
check(
    reused.memory_id == applied.memory_id
    and len(w02_store.list(subject="anders", predicate="new_slot")) == 1,
    "W02 reuse does not create another durable row",
)

conflict_a = w02_candidate(predicate="batch_conflict", value="A")
conflict_b = w02_candidate(predicate="batch_conflict", value="B")
conflict_plan = plan_legacy_consolidation(w02_store, [conflict_a, conflict_b])
check(
    len(conflict_plan.decisions) == 2
    and all(item.action == ACTION_REVIEW for item in conflict_plan.decisions),
    "W02 conflicting same-slot candidate values fail closed to review",
)

base_pending_slot = w02_store.create(
    subject="anders",
    predicate="pending_alternative",
    value="stable",
    sensitivity="private",
    source_type="user_explicit",
)
pending_candidate = w02_candidate(
    predicate="pending_alternative",
    value="maybe",
    source_type="inferred",
    confidence=0.6,
    review_status="pending",
)
pending_plan = plan_legacy_consolidation(w02_store, [pending_candidate])
check(
    len(pending_plan.decisions) == 1
    and pending_plan.decisions[0].action == ACTION_CREATE,
    "W02 pending inference may be stored for review but never supersedes confirmed memory",
)
pending_applied = apply_legacy_consolidation_decision(
    w02_store,
    pending_plan.decisions[0],
)
check(
    w02_store.get(base_pending_slot.id).lifecycle_status == "active"
    and w02_store.get(pending_applied.memory_id or "").review_status == "pending",
    "W02 pending alternative preserves the confirmed durable row",
)
ambiguous_after_pending = plan_legacy_consolidation(
    w02_store,
    [w02_candidate(predicate="pending_alternative", value="new explicit")],
)
check(
    ambiguous_after_pending.decisions[0].action == ACTION_REVIEW,
    "W02 refuses automatic replacement once a slot has multiple active rows",
)

stale_old = w02_store.create(
    subject="anders",
    predicate="stale_fact",
    value="old",
    sensitivity="private",
    source_type="user_explicit",
)
stale_candidate = w02_candidate(predicate="stale_fact", value="new")
stale_plan = plan_legacy_consolidation(w02_store, [stale_candidate])
check(
    stale_plan.decisions[0].action == ACTION_SUPERSEDE,
    "W02 confirmed explicit fact can plan one private stale-fact supersede",
)
intermediate = w02_store.correct(stale_old.id, value="intermediate")
try:
    apply_legacy_consolidation_decision(w02_store, stale_plan.decisions[0])
    stale_refused = False
except MemoryConsolidationApplyError:
    stale_refused = True
check(stale_refused, "W02 stale optimistic supersede plan fails closed")
check(
    [item.id for item in w02_store.list(subject="anders", predicate="stale_fact")]
    == [intermediate.id],
    "W02 stale-plan refusal does not create a third version",
)

old_version = w02_store.create(
    subject="anders",
    predicate="versioned_fact",
    value="v1",
    sensitivity="private",
    source_type="user_explicit",
)
version_candidate = w02_candidate(predicate="versioned_fact", value="v2")
version_plan = plan_legacy_consolidation(w02_store, [version_candidate])
version_applied = apply_legacy_consolidation_decision(
    w02_store,
    version_plan.decisions[0],
)
version_history = w02_store.history("anders", "versioned_fact")
check(
    version_applied.action == ACTION_SUPERSEDE
    and version_applied.superseded_id == old_version.id
    and [item.lifecycle_status for item in version_history] == ["superseded", "active"]
    and version_history[-1].supersedes_id == old_version.id,
    "W02 persistence preserves version/supersede history instead of overwriting",
)

public_existing = w02_store.create(
    subject="anders",
    predicate="sensitivity_guard",
    value="same",
    sensitivity="public",
    source_type="user_explicit",
)
sensitivity_plan = plan_legacy_consolidation(
    w02_store,
    [w02_candidate(predicate="sensitivity_guard", value="same")],
)
check(
    sensitivity_plan.decisions[0].action == ACTION_REVIEW
    and w02_store.get(public_existing.id).sensitivity == "public",
    "W02 refuses to reuse an under-classified durable row for a private candidate",
)

secret_base = w02_store.create(
    subject="anders",
    predicate="secret_guard",
    value="public-ish old value",
    sensitivity="private",
    source_type="user_explicit",
)
secret_candidate = w02_candidate(
    predicate="secret_guard",
    value="sk-example-secret-12345678",
    sensitivity="secret",
    source_type="user_explicit",
    review_status="pending",
)
secret_plan = plan_legacy_consolidation(w02_store, [secret_candidate])
check(
    secret_plan.decisions[0].action == ACTION_REVIEW
    and w02_store.get(secret_base.id).lifecycle_status == "active",
    "W02 secret candidates stay pending and cannot automatically replace durable facts",
)

new_slot_candidate = w02_candidate(predicate="create_race", value="planned")
create_race_plan = plan_legacy_consolidation(w02_store, [new_slot_candidate])
w02_store.create(
    subject="anders",
    predicate="create_race",
    value="concurrent",
    sensitivity="private",
    source_type="user_explicit",
)
try:
    apply_legacy_consolidation_decision(w02_store, create_race_plan.decisions[0])
    create_race_refused = False
except MemoryConsolidationApplyError:
    create_race_refused = True
check(create_race_refused, "W02 new-slot create is revalidated before persistence")

try:
    MemoryConsolidator().plan(
        [w02_candidate(predicate=f"cap-{idx}", value=str(idx)) for idx in range(MAX_CONSOLIDATION_CANDIDATES + 1)],
        [],
    )
    candidate_cap_refused = False
except MemoryConsolidationError:
    candidate_cap_refused = True
check(candidate_cap_refused, "W02 candidate batches are hard-capped before planning")

record_probe = w02_store.get(public_existing.id)
try:
    MemoryConsolidator().plan(
        [w02_candidate(predicate="record_cap", value="x")],
        [record_probe] * (MAX_CONSOLIDATION_RECORDS + 1),
    )
    record_cap_refused = False
except MemoryConsolidationError:
    record_cap_refused = True
check(record_cap_refused, "W02 existing-memory input is hard-capped")

try:
    MemoryConsolidator().plan(
        [w02_candidate(predicate="malformed", value="x")],
        [replace(record_probe, lifecycle_status="superseded")],
    )
    malformed_refused = False
except MemoryConsolidationError:
    malformed_refused = True
check(malformed_refused, "W02 rejects non-active existing snapshots fail-closed")

w02_store.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)