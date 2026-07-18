"""A claimed occurrence re-checks the live grant before ToolGate (T-013).

claim_due returns a snapshot, and the runner executes the batch sequentially --
minutes can pass between the claim and the execution of the last claim in a
tick. Before this, pausing, renewing or deleting a schedule in that gap changed
nothing: the stale snapshot ran anyway. The user's pause did not stop in-flight
work.

Now every user-intent mutation bumps a revision, the claim carries the revision
it was taken under, and the runner re-reads the live grant immediately before
ToolGate. A mismatch -- deleted, paused, or a different revision/approval --
cancels the occurrence: budget slot refunded, job closed 'cancelled' with the
reason, and the schedule NOT disabled, because the user's change was deliberate
and the schedule should keep running under its new terms.

Run: PYTHONPATH=worker python3 tests/worker_schedule_revoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.jobs import JobStore  # noqa: E402
from app.schedule_runner import SchedulerRunner  # noqa: E402
from app.scheduler import ScheduleStore  # noqa: E402
from app import tools as T  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def make_env():
    td = tempfile.mkdtemp(prefix="revoke-")
    schedules = ScheduleStore(path=os.path.join(td, "schedules.db"))
    jobs = JobStore(os.path.join(td, "jobs.db"))
    audit = T.AuditLog(os.path.join(td, "audit.db"))
    gate = T.ToolGate(audit=audit, state_file=None)
    gate.set_enabled(True)
    runner = SchedulerRunner(schedules, jobs, gate, feature_enabled=lambda: True)
    return schedules, jobs, gate, runner


NOW = 1_000_000.0


def _runs_used(store, sid):
    return store.get(sid).runs_used


def _occ_status(store, claim_id):
    row = store._conn.execute(
        "SELECT status FROM occurrences WHERE claim_id=?", (claim_id,)
    ).fetchone()
    return row["status"] if row else None


# --- pause after claim, before execution -> cancelled, refunded, not disabled
st, jb, gt, rn = make_env()
sched = st.create("rig_status", {}, "every:60", now=NOW)
claim = st.claim_due(now=NOW + 61)[0]
check(_runs_used(st, sched.schedule_id) == 1, "the claim reserved its slot")
st.set_enabled(sched.schedule_id, False, now=NOW + 62)
jid = jb.create("schedule:rig_status", detail=f"occ={claim.claim_id}")
jb.update(jid, status="running", detail=f"occ={claim.claim_id}")
st.bind_job(claim.claim_id, jid)
outcome = rn._run_claim(claim, jid, NOW + 63)
check(outcome == "blocked",
      "a pause between claim and execution stops the in-flight occurrence -- "
      "the user's pause actually pauses")
check(_runs_used(st, sched.schedule_id) == 0,
      "the reserved budget slot is refunded -- the run did not happen")
check(_occ_status(st, claim.claim_id) == "released",
      "the occurrence resolves released, not left dangling")
job = jb.get(jid)
check(job and job["status"] == "cancelled",
      "the job closes 'cancelled' -- a user decision, not a failure")
check("pauset" in (job.get("detail") or ""),
      "and the detail says why, so the audit trail is legible")
check(st.get(sched.schedule_id) is not None,
      "the schedule itself survives -- the change was deliberate, not an error")

# --- pause -> resume cycle: revision is what catches it ---------------------
# After resume, enabled is True again and the fingerprint is unchanged. Only the
# revision reveals that the claim predates the pause. Resume already reset
# due_at to a fresh future occurrence; the pre-pause claim is stale and must
# not fire.
st, jb, gt, rn = make_env()
sched = st.create("rig_status", {}, "every:60", now=NOW)
claim = st.claim_due(now=NOW + 61)[0]
st.set_enabled(sched.schedule_id, False, now=NOW + 62)
st.set_enabled(sched.schedule_id, True, now=NOW + 63)
guard = st.current_guard(sched.schedule_id)
check(guard["enabled"] and guard["revision"] == claim.revision + 2,
      "pause and resume each bump the revision -- two user actions, two bumps")
jid = jb.create("schedule:rig_status", detail=f"occ={claim.claim_id}")
st.bind_job(claim.claim_id, jid)
outcome = rn._run_claim(claim, jid, NOW + 64)
check(outcome == "blocked" and _runs_used(st, sched.schedule_id) == 0,
      "a claim from before the pause does not fire after the resume -- enabled "
      "and approval look fine; the revision is what catches it")

# --- deleted after claim -> cancelled safely --------------------------------
st, jb, gt, rn = make_env()
sched = st.create("rig_status", {}, "every:60", now=NOW)
claim = st.claim_due(now=NOW + 61)[0]
st.delete(sched.schedule_id)
jid = jb.create("schedule:rig_status", detail=f"occ={claim.claim_id}")
st.bind_job(claim.claim_id, jid)
outcome = rn._run_claim(claim, jid, NOW + 63)
check(outcome == "blocked",
      "a schedule deleted after the claim does not execute its stale snapshot")
check(_occ_status(st, claim.claim_id) == "released",
      "the orphaned occurrence still resolves cleanly")

# --- the batch gap, end to end: executing A pauses B mid-tick ---------------
# Two schedules due in one tick. A's tool pauses B as its side effect. The
# runner claimed BOTH up front; without the guard, B's stale claim would still
# run. With it, B is cancelled and refunded in the same tick.
st, jb, gt, rn = make_env()
b = st.create("rig_status", {}, "every:60", now=NOW)

_pause_name = "_revoke_pauser"
T.REGISTRY[_pause_name] = T.Tool(
    name=_pause_name, description="pauses schedule b", risk="read",
    run=lambda args: str(st.set_enabled(b.schedule_id, False, now=NOW + 62)),
)
try:
    # A must execute FIRST for the pause to land before B's turn. Claims run in
    # due_at order, so give A an earlier creation time -> earlier due_at.
    a = st.create(_pause_name, {}, "every:60", now=NOW - 10)
    rn.registry = dict(T.REGISTRY)
    tick = rn.run_once(now=NOW + 61)
    check(tick.claimed == 2 and tick.completed == 1 and tick.blocked == 1,
          "one tick: A executes (and pauses B); B's already-claimed occurrence "
          "is cancelled instead of running against the user's pause")
    check(_runs_used(st, b.schedule_id) == 0,
          "B's reserved slot is refunded in the same tick")
    check(st.get(b.schedule_id) is not None
          and not st.get(b.schedule_id).enabled,
          "B stays paused exactly as the user (via A's side effect) asked")
finally:
    T.REGISTRY.pop(_pause_name, None)

# --- the normal path is untouched -------------------------------------------
st, jb, gt, rn = make_env()
sched = st.create("rig_status", {}, "every:60", now=NOW)
tick = rn.run_once(now=NOW + 61)
check(tick.completed == 1,
      "an unmodified schedule executes exactly as before -- the guard only "
      "fires on a real change")

print(f"\n===== SCHEDULE REVOKE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
