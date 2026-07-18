"""The occurrence-ledger: execution truth is durable from claim, not finish (F-902/F-903).

Before this, a claim advanced due_at and lived only in memory. Two windows leaked:

  F-903 -- a crash between the claim commit and job creation left an INVISIBLE
  skip: due_at already past the occurrence, no job, no audit, no recovery.

  F-902 -- the run budget was spent only AFTER execution, so a long run or a
  restart could exceed max_runs.

The fix reserves a durable occurrence row and a budget slot in the SAME
transaction that advances due_at, then reconciles: executed on success, released
(slot refunded) on a run that did not happen, abandoned (slot refunded) at
startup for a claim whose worker died in the gap. These properties are driven
here directly against a real on-disk store.

Run: PYTHONPATH=worker python3 tests/worker_occurrence_ledger.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.scheduler import ScheduleStore  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def _store():
    path = os.path.join(tempfile.mkdtemp(prefix="occ-ledger-"), "sched.db")
    return ScheduleStore(path=path)


def _occ_status(store, claim_id):
    row = store._conn.execute(
        "SELECT status FROM occurrences WHERE claim_id=?", (claim_id,)
    ).fetchone()
    return row["status"] if row else None


def _runs_used(store, sid):
    return store.get(sid).runs_used


NOW = 1_000_000.0

# --- a claim reserves a durable occurrence AND a budget slot (F-902/F-903) ---
store = _store()
s = store.create("rig_status", {}, "every:60", now=NOW)
claims = store.claim_due(now=NOW + 61)
check(len(claims) == 1, "a due schedule yields one claim")
claim = claims[0]
check(claim.claim_id, "the claim carries a claim_id tying it to the ledger")
check(_occ_status(store, claim.claim_id) == "reserved",
      "the occurrence is durable and 'reserved' the instant it is claimed -- "
      "not an in-memory-only claim that a crash would lose")
check(_runs_used(store, s.schedule_id) == 1,
      "the budget slot is reserved AT CLAIM, before execution (F-902)")

# --- success resolves the occurrence, budget stays spent --------------------
store.record_claim_result(s.schedule_id, ran=True, claim_id=claim.claim_id)
check(_occ_status(store, claim.claim_id) == "executed",
      "a run that happened resolves the occurrence to executed")
check(_runs_used(store, s.schedule_id) == 1,
      "success does not double-count -- the slot was already reserved")

# --- a run that did NOT happen refunds its slot -----------------------------
store2 = _store()
s2 = store2.create("rig_status", {}, "every:60", now=NOW)
c2 = store2.claim_due(now=NOW + 61)[0]
check(_runs_used(store2, s2.schedule_id) == 1, "slot reserved at claim")
store2.record_claim_result(s2.schedule_id, ran=False, claim_id=c2.claim_id)
check(_occ_status(store2, c2.claim_id) == "released",
      "a refused/failed run marks the occurrence released")
check(_runs_used(store2, s2.schedule_id) == 0,
      "and returns the reserved slot -- a schedule is never charged for a run "
      "it did not make")

# --- a double release cannot refund twice -----------------------------------
store2.record_claim_result(s2.schedule_id, ran=False, claim_id=c2.claim_id)
check(_runs_used(store2, s2.schedule_id) == 0,
      "releasing an already-released occurrence does not refund a second slot")

# --- budget cannot be exceeded across claims (F-902) ------------------------
# max_runs=1: the first claim reserves the only slot. The next due occurrence is
# still claimed (so the runner can disable+audit it) but reserves NO further
# slot, so runs_used never climbs past max_runs.
store3 = _store()
s3 = store3.create("rig_status", {}, "every:60", max_runs=1, now=NOW)
first = store3.claim_due(now=NOW + 61)[0]
check(_runs_used(store3, s3.schedule_id) == 1, "first claim reserves the one slot")
second = store3.claim_due(now=NOW + 122)[0]
check(_runs_used(store3, s3.schedule_id) == 1,
      "a claim past budget reserves NO further slot -- max_runs cannot be "
      "exceeded even under back-to-back claims (F-902)")
check(_occ_status(store3, second.claim_id) == "reserved_noslot",
      "the over-budget claim is marked reserved_noslot, so it still reaches the "
      "runner's refusal path but recovery will not refund a slot it never took")

# --- startup recovery refunds a slot whose worker died mid-claim (F-903) ----
# Simulate the crash: claim (reserving a slot) and then never resolve it.
store4 = _store()
s4 = store4.create("rig_status", {}, "every:60", now=NOW)
crashed = store4.claim_due(now=NOW + 61)[0]
check(_occ_status(store4, crashed.claim_id) == "reserved"
      and _runs_used(store4, s4.schedule_id) == 1,
      "before recovery: a reserved occurrence with a spent slot")
recovered = store4.recover_reserved(now=NOW + 200)
check(crashed.claim_id in recovered,
      "startup recovery finds the occurrence whose worker died mid-claim")
check(_occ_status(store4, crashed.claim_id) == "abandoned",
      "and marks it abandoned -- no longer an invisible skip (F-903)")
check(_runs_used(store4, s4.schedule_id) == 0,
      "and returns its budget slot, so a crash does not permanently burn a run")

# --- recovery is idempotent and leaves resolved occurrences alone -----------
again = store4.recover_reserved(now=NOW + 300)
check(again == [] and _runs_used(store4, s4.schedule_id) == 0,
      "a second recovery pass touches nothing -- only 'reserved' rows, refund "
      "bounded at zero")

# An executed occurrence must never be abandoned by recovery.
store5 = _store()
s5 = store5.create("rig_status", {}, "every:60", now=NOW)
done = store5.claim_due(now=NOW + 61)[0]
store5.record_claim_result(s5.schedule_id, ran=True, claim_id=done.claim_id)
store5.recover_reserved(now=NOW + 500)
check(_occ_status(store5, done.claim_id) == "executed"
      and _runs_used(store5, s5.schedule_id) == 1,
      "recovery leaves an executed occurrence and its spent budget untouched")

print(f"\n===== OCCURRENCE LEDGER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
