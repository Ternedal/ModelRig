from __future__ import annotations

import os
import tempfile
import time

from app.agent3.memory import MemoryNotFound, MemoryStore, MemoryStoreError

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

store.close()
reopened = MemoryStore(path)
check(reopened.get(inferred.id).review_status == "confirmed", "memory state persists across reopen")
reopened.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
