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

# --- crash recovery: three different deaths, three deterministic ends (T-012)
# Recovery must consult EVIDENCE. A worker can die (W1) before the job exists,
# (W2) after the job but before ToolGate ran, or (W3) AFTER ToolGate ran the
# side effect but before the result was recorded. W1/W2: nothing ran -> refund
# the slot, close any dangling job. W3: it RAN -> the slot must STAY SPENT,
# because refunding a run that happened is exactly how max_runs gets exceeded
# via crash -- and the job is reconciled to completed. The audit is the
# evidence: ToolGate writes outcome='executed' under a conversation id carrying
# the claim_id.
import tempfile as _tf

from app.jobs import JobStore as _JobStore  # noqa: E402
from app.schedule_runner import (  # noqa: E402
    SchedulerRunner as _Runner,
    _occurrence_conversation as _occ_conv,
)
from app import tools as _T  # noqa: E402


def _env():
    td = _tf.mkdtemp(prefix="occ-recover-")
    schedules = ScheduleStore(path=os.path.join(td, "schedules.db"))
    jobs = _JobStore(os.path.join(td, "jobs.db"))
    audit = _T.AuditLog(os.path.join(td, "audit.db"))
    gate = _T.ToolGate(audit=audit, state_file=None)
    gate.set_enabled(True)
    runner = _Runner(schedules, jobs, gate, feature_enabled=lambda: True)
    return schedules, jobs, gate, runner


# W1: died right after the claim -- no job, no execution.
st, jb, gt, rn = _env()
w1 = st.create("rig_status", {}, "every:60", now=NOW)
c_w1 = st.claim_due(now=NOW + 61)[0]
out = rn.recover_interrupted(now=NOW + 200)
check(c_w1.claim_id in out["abandoned"],
      "W1 (died before the job): recovery abandons the occurrence")
check(_occ_status(st, c_w1.claim_id) == "abandoned"
      and _runs_used(st, w1.schedule_id) == 0,
      "W1: the slot is refunded -- nothing ran, the schedule is not charged")

# recovery is idempotent
again = rn.recover_interrupted(now=NOW + 300)
check(again["abandoned"] == [] and again["executed"] == [],
      "a second recovery pass touches nothing -- only unresolved rows")

# W2: died after the job was created and bound, before ToolGate ran.
st, jb, gt, rn = _env()
w2 = st.create("rig_status", {}, "every:60", now=NOW)
c_w2 = st.claim_due(now=NOW + 61)[0]
jid_w2 = jb.create("schedule:rig_status", detail=f"occ={c_w2.claim_id}")
jb.update(jid_w2, status="running", detail=f"occ={c_w2.claim_id}")
st.bind_job(c_w2.claim_id, jid_w2)
out = rn.recover_interrupted(now=NOW + 200)
check(c_w2.claim_id in out["abandoned"]
      and _runs_used(st, w2.schedule_id) == 0,
      "W2 (died before execution): abandoned and refunded, same as W1")
job_w2 = jb.get(jid_w2)
check(job_w2 and job_w2["status"] == "failed",
      "W2: the dangling job is closed failed-terminal -- it does not advertise "
      "'running' forever")

# W3: died AFTER ToolGate executed the side effect, before recording. Simulate
# by writing the exact audit row ToolGate writes at execution.
st, jb, gt, rn = _env()
w3 = st.create("rig_status", {}, "every:60", now=NOW)
c_w3 = st.claim_due(now=NOW + 61)[0]
jid_w3 = jb.create("schedule:rig_status", detail=f"occ={c_w3.claim_id}")
jb.update(jid_w3, status="running", detail=f"occ={c_w3.claim_id}")
st.bind_job(c_w3.claim_id, jid_w3)
gt.audit.record(
    tool="rig_status", args={}, risk="read", outcome="executed",
    conversation_id=_occ_conv(w3.schedule_id, c_w3.claim_id),
    origin="schedule",
)
out = rn.recover_interrupted(now=NOW + 200)
check(c_w3.claim_id in out["executed"],
      "W3 (died AFTER the side effect): the audit is the evidence, and "
      "recovery sees it")
check(_occ_status(st, c_w3.claim_id) == "executed"
      and _runs_used(st, w3.schedule_id) == 1,
      "W3: the slot STAYS SPENT -- refunding a run that happened is how "
      "max_runs gets exceeded via crash, and that door is closed")
job_w3 = jb.get(jid_w3)
check(job_w3 and job_w3["status"] == "completed",
      "W3: the job is reconciled to completed with the degraded-bookkeeping "
      "truth, not left running")

# A refusal audit row is NOT execution evidence.
st, jb, gt, rn = _env()
w4 = st.create("rig_status", {}, "every:60", now=NOW)
c_w4 = st.claim_due(now=NOW + 61)[0]
gt.audit.record(
    tool="rig_status", args={}, risk="read", outcome="blocked",
    conversation_id=_occ_conv(w4.schedule_id, c_w4.claim_id),
    origin="schedule",
)
out = rn.recover_interrupted(now=NOW + 200)
check(c_w4.claim_id in out["abandoned"]
      and _runs_used(st, w4.schedule_id) == 0,
      "a blocked/denied audit row is a refusal, not execution -- recovery still "
      "refunds")

# --- F-1002: the UNKNOWN window -- attempt without executed ------------------
# ToolGate audits 'executed' only AFTER the tool ran. The runner now writes an
# ATTEMPT row immediately before propose, so recovery can tell three deaths
# apart: no attempt (never ran -> refund), attempt+executed (ran -> keep),
# attempt alone (MAY have run -> the one case that must NOT refund). Refunding
# it is how max_runs=N produced N+1 real writes: the side effect happened, the
# slot came back, and the next cadence spent it again.

# The headline property, driven directly: a WRITE that dies in the sliver.
st, jb, gt, rn = _env()
w6 = st.create("note_append", {"text": "x"}, "every:60",
               approve_write=True, max_runs=1, now=NOW)
c_w6 = st.claim_due(now=NOW + 61)[0]
jid_w6 = jb.create("schedule:note_append", detail=f"occ={c_w6.claim_id}")
jb.update(jid_w6, status="running", detail=f"occ={c_w6.claim_id}")
st.bind_job(c_w6.claim_id, jid_w6)
gt.audit.record(
    tool="note_append", args={"text": "x"}, risk="write", outcome="attempt",
    conversation_id=_occ_conv(w6.schedule_id, c_w6.claim_id),
    origin="schedule",
)
out = rn.recover_interrupted(now=NOW + 200)
check(c_w6.claim_id in out["unknown"],
      "a write that died between attempt and executed is UNKNOWN -- not "
      "abandoned, not executed")
check(_occ_status(st, c_w6.claim_id) == "unknown"
      and _runs_used(st, w6.schedule_id) == 1,
      "the budget slot STAYS SPENT -- refunding it is exactly how max_runs=N "
      "became N+1 real writes (F-1002)")
sched_after = st.get(w6.schedule_id)
check(sched_after is not None and not sched_after.enabled,
      "and the grant is PAUSED until a human settles what actually happened")
job_w6 = jb.get(jid_w6)
check(job_w6 and job_w6["status"] == "failed"
      and "UKENDT" in (job_w6.get("detail") or ""),
      "the job says plainly that the outcome is unknown and the slot was kept")
later = st.claim_due(now=NOW + 400)
check(all(c.schedule.schedule_id != w6.schedule_id for c in later),
      "no later cadence can spend anything: the paused grant claims nothing "
      "-- the N+1 door is closed from both sides")

# Risk-aware: a READ in the same window has no side effect worth guarding.
st, jb, gt, rn = _env()
w7 = st.create("rig_status", {}, "every:60", now=NOW)
c_w7 = st.claim_due(now=NOW + 61)[0]
gt.audit.record(
    tool="rig_status", args={}, risk="read", outcome="attempt",
    conversation_id=_occ_conv(w7.schedule_id, c_w7.claim_id),
    origin="schedule",
)
out = rn.recover_interrupted(now=NOW + 200)
check(c_w7.claim_id in out["abandoned"]
      and _runs_used(st, w7.schedule_id) == 0
      and st.get(w7.schedule_id).enabled,
      "a READ in the unknown window refunds like a clean death -- no side "
      "effect to guard, availability preferred, grant stays enabled")

# attempt + executed together is simply executed (the marker changes nothing).
st, jb, gt, rn = _env()
w8 = st.create("note_append", {"text": "x"}, "every:60",
               approve_write=True, now=NOW)
c_w8 = st.claim_due(now=NOW + 61)[0]
for oc in ("attempt", "executed"):
    gt.audit.record(
        tool="note_append", args={"text": "x"}, risk="write", outcome=oc,
        conversation_id=_occ_conv(w8.schedule_id, c_w8.claim_id),
        origin="schedule",
    )
out = rn.recover_interrupted(now=NOW + 200)
check(c_w8.claim_id in out["executed"]
      and _runs_used(st, w8.schedule_id) == 1
      and st.get(w8.schedule_id).enabled,
      "attempt followed by executed is just executed -- slot spent, grant "
      "untouched")

# --- the reserve-at-claim off-by-one (found by valideringsplan #7) -----------
# From 1.58.116 the claimed snapshot's runs_used INCLUDES this occurrence's
# reservation, but the refusal still compared >= max_runs on it. So max_runs=1
# refused its own FIRST run and disabled itself having executed zero times,
# and every schedule got max_runs-1 executions. The budget truth now rides on
# the claim (reserved vs reserved_noslot). These pin the honest contract:
# max_runs=N means exactly N executions, then a legible refusal.
st, jb, gt, rn = _env()
b1 = st.create("rig_status", {}, "every:60", max_runs=1, now=NOW)
t = rn.run_once(now=NOW + 61)
check(t.completed == 1 and _runs_used(st, b1.schedule_id) == 1,
      "max_runs=1 executes its ONE run -- the last budgeted occurrence is a "
      "legitimate run, not an exhaustion")
t2 = rn.run_once(now=NOW + 122)
after = st.get(b1.schedule_id)
check(t2.blocked == 1 and after is not None and not after.enabled,
      "the SECOND occurrence is the exhausted one: blocked and disabled "
      "through the refusal path")
jobs_b1 = [jb.get(r["job_id"]) for r in st._conn.execute(
    "SELECT job_id FROM occurrences WHERE schedule_id=? AND job_id IS NOT NULL",
    (b1.schedule_id,)).fetchall()]
check(any(j and "budget" in (j.get("detail") or "") for j in jobs_b1),
      "and the reason the user reads says budget, with the honest count")

st, jb, gt, rn = _env()
b2 = st.create("rig_status", {}, "every:60", max_runs=2, now=NOW)
rn.run_once(now=NOW + 61)
rn.run_once(now=NOW + 122)
rn.run_once(now=NOW + 183)
executed = st._conn.execute(
    "SELECT COUNT(*) c FROM occurrences WHERE schedule_id=? "
    "AND status='executed'", (b2.schedule_id,)).fetchone()["c"]
check(executed == 2 and _runs_used(st, b2.schedule_id) == 2,
      "max_runs=2 executes exactly TWO runs across cadences -- N means N, "
      "not N-1")

# The normal completed path leaves nothing for recovery, and run_once binds the
# job so the occurrence can name it.
st, jb, gt, rn = _env()
w5 = st.create("rig_status", {}, "every:60", now=NOW)
tick = rn.run_once(now=NOW + 61)
check(tick.completed == 1, "a live tick completes normally")
occ_rows = st._conn.execute(
    "SELECT status, job_id FROM occurrences").fetchall()
check(len(occ_rows) == 1 and occ_rows[0]["status"] == "executed"
      and occ_rows[0]["job_id"],
      "run_once binds the job to the occurrence and resolves it executed -- "
      "job, audit, outcome and recovery all reference the same claim")
conv_live = _occ_conv(w5.schedule_id,
                      st._conn.execute(
                          "SELECT claim_id FROM occurrences").fetchone()["claim_id"])
check(gt.audit.has_attempt(conv_live) and gt.audit.has_execution(conv_live),
      "a live tick leaves BOTH the attempt marker and the executed row -- the "
      "marker is written in the real path, not only in simulations")
out = rn.recover_interrupted(now=NOW + 200)
check(out["executed"] == [] and out["abandoned"] == []
      and out["unknown"] == [],
      "recovery finds nothing after a clean run")

print(f"\n===== OCCURRENCE LEDGER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
