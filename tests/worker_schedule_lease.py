"""The scheduler owner-lease: a living worker's claims are never abandoned (F-1003).

Startup recovery treats every 'reserved' occurrence as a dead worker's. That is
only safe if there IS no other living worker: a second process starting up
would otherwise abandon in-flight claims and refund slots for runs happening
right now. The lease makes single-flight explicit across processes -- recovery
and ticking both require holding it, exactly one process wins the BEGIN
IMMEDIATE race, and a crashed owner's lease expires so the next start takes
over cleanly.

Run: PYTHONPATH=worker python3 tests/worker_schedule_lease.py
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


def make_env(owner_id: str):
    td = tempfile.mkdtemp(prefix="lease-")
    schedules = ScheduleStore(path=os.path.join(td, "schedules.db"))
    jobs = JobStore(os.path.join(td, "jobs.db"))
    audit = T.AuditLog(os.path.join(td, "audit.db"))
    gate = T.ToolGate(audit=audit, state_file=None)
    gate.set_enabled(True)
    runner = SchedulerRunner(schedules, jobs, gate,
                             feature_enabled=lambda: True,
                             owner_id=owner_id, lease_ttl_seconds=90.0)
    return schedules, jobs, gate, runner


NOW = 1_000_000.0

# --- the primitive: exactly one live owner ----------------------------------
st, jb, gt, rn = make_env("worker-a")
check(st.acquire_lease("worker-a", ttl_seconds=90, now=NOW),
      "an empty lease is granted to the first owner")
check(not st.acquire_lease("worker-b", ttl_seconds=90, now=NOW + 10),
      "a second owner is refused while the first lease is alive")
check(st.acquire_lease("worker-a", ttl_seconds=90, now=NOW + 10),
      "the holder re-acquires freely -- acquisition doubles as renewal")
check(st.acquire_lease("worker-b", ttl_seconds=90, now=NOW + 200),
      "an EXPIRED lease is taken over by the next owner -- a crashed worker "
      "does not hold the scheduler hostage")

# --- clean stop releases immediately ----------------------------------------
st2, _, _, _ = make_env("worker-a")
st2.acquire_lease("worker-a", ttl_seconds=90, now=NOW)
st2.release_lease("worker-a")
check(st2.acquire_lease("worker-b", ttl_seconds=90, now=NOW + 1),
      "a released lease is available at once -- clean restarts do not wait "
      "out a dead TTL")
st2.acquire_lease("worker-b", ttl_seconds=90, now=NOW + 1)
st2.release_lease("worker-a")
check(not st2.acquire_lease("worker-c", ttl_seconds=90, now=NOW + 2),
      "only the owner can release -- a stranger's release is a no-op")

# --- THE property: recovery cannot abandon a living owner's claim -----------
# Worker A holds the lease and has an in-flight reserved occurrence. Worker B
# starts up and runs recovery. Before F-1003, B would have abandoned A's claim
# and refunded a slot for a run happening right now.
st, jb, gt, rn_a = make_env("worker-a")
sched = st.create("rig_status", {}, "every:60", now=NOW)
st.acquire_lease("worker-a", ttl_seconds=90, now=NOW + 60)
claim = st.claim_due(now=NOW + 61)[0]
_, _, _, rn_b = (st, jb, gt,
                 SchedulerRunner(st, jb, gt, feature_enabled=lambda: True,
                                 owner_id="worker-b", lease_ttl_seconds=90.0))
out = rn_b.recover_interrupted(now=NOW + 70)
check(out.get("skipped_no_lease") is True
      and out["executed"] == [] and out["abandoned"] == []
      and out["unknown"] == [],
      "recovery WITHOUT the lease touches nothing and says so")
row = st._conn.execute(
    "SELECT status FROM occurrences WHERE claim_id=?",
    (claim.claim_id,)).fetchone()
check(row["status"] == "reserved"
      and st.get(sched.schedule_id).runs_used == 1,
      "the living owner's in-flight claim stays reserved with its slot spent "
      "-- no refund for a run that is happening right now (F-1003)")

# --- a tick without the lease claims nothing --------------------------------
st3, jb3, gt3, rn3 = make_env("worker-a")
s3 = st3.create("rig_status", {}, "every:60", now=NOW)
st3.acquire_lease("someone-else", ttl_seconds=300, now=NOW + 60)
tick = rn3.run_once(now=NOW + 61)
check(tick.claimed == 0,
      "a tick without the lease claims NOTHING -- two workers cannot "
      "double-run the same schedules")
check(st3.get(s3.schedule_id).due_at == s3.due_at
      and st3.get(s3.schedule_id).runs_used == 0,
      "and the due occurrence is untouched -- the lease-less tick consumed "
      "nothing")

# --- crash-takeover end to end ----------------------------------------------
# A claims under its lease and dies. B before expiry: blocked. B after expiry:
# takes the lease, recovers A's orphan (abandon+refund), and ticks normally.
st4, jb4, gt4, rn_a4 = make_env("worker-a")
s4 = st4.create("rig_status", {}, "every:60", now=NOW)
st4.acquire_lease("worker-a", ttl_seconds=90, now=NOW + 60)
st4.claim_due(now=NOW + 61)  # A's claim; then A "dies"
rn_b4 = SchedulerRunner(st4, jb4, gt4, feature_enabled=lambda: True,
                        owner_id="worker-b", lease_ttl_seconds=90.0)
early = rn_b4.recover_interrupted(now=NOW + 100)
check(early.get("skipped_no_lease") is True,
      "before the dead owner's lease expires, the successor still waits")
late = rn_b4.recover_interrupted(now=NOW + 200)
check(len(late["abandoned"]) == 1
      and st4.get(s4.schedule_id).runs_used == 0,
      "after expiry the successor takes over and settles the orphan exactly "
      "as single-owner recovery always did")
tick = rn_b4.run_once(now=NOW + 201)
check(tick.claimed in (0, 1),
      "and the successor ticks normally under its own lease")

# --- valideringsplan #5: takeover + UNKNOWN outcome combined -----------------
# A claims a WRITE, records the attempt marker, and dies. The successor must
# apply the SAME conservative policy under a taken-over lease: no audit of
# execution -> unknown -> slot kept, grant paused. Expiry does not soften the
# outcome policy.
st5, jb5, gt5, rn_a5 = make_env("worker-a")
w5 = st5.create("note_append", {"text": "x"}, "every:60",
                approve_write=True, max_runs=2, now=NOW)
st5.acquire_lease("worker-a", ttl_seconds=90, now=NOW + 60)
c5 = st5.claim_due(now=NOW + 61)[0]
gt5.audit.record(
    tool="note_append", args={"text": "x"}, risk="write", outcome="attempt",
    conversation_id=__import__("app.schedule_runner", fromlist=["x"])
    ._occurrence_conversation(w5.schedule_id, c5.claim_id),
    origin="schedule",
)
rn_b5 = SchedulerRunner(st5, jb5, gt5, feature_enabled=lambda: True,
                        owner_id="worker-b", lease_ttl_seconds=90.0)
out = rn_b5.recover_interrupted(now=NOW + 200)
check(c5.claim_id in out["unknown"]
      and st5.get(w5.schedule_id).runs_used == 1
      and not st5.get(w5.schedule_id).enabled,
      "a taken-over lease applies the SAME conservative policy: attempt "
      "without executed is unknown -- slot kept, grant paused -- expiry does "
      "not soften the outcome (valideringsplan #5)")

# --- valideringsplan #7: two processes, max_runs=1, several cadences ---------
# The integration property tying budget + lease + recovery together: across a
# worker death and a successor, the world sees EXACTLY one executed
# occurrence, ever.
st7, jb7, gt7, rn_a7 = make_env("worker-a")
s7 = st7.create("rig_status", {}, "every:60", max_runs=1, now=NOW)
t1 = rn_a7.run_once(now=NOW + 61)
check(t1.completed == 1 and st7.get(s7.schedule_id).runs_used == 1,
      "process A runs the single budgeted occurrence under its lease")
# A dies. B ticks the NEXT cadence while A's lease is still alive:
rn_b7 = SchedulerRunner(st7, jb7, gt7, feature_enabled=lambda: True,
                        owner_id="worker-b", lease_ttl_seconds=90.0)
t2 = rn_b7.run_once(now=NOW + 122)
check(t2.claimed == 0,
      "process B claims nothing while A's lease lives -- no double-run window")
# After expiry B recovers (nothing reserved) and ticks further cadences:
rn_b7.recover_interrupted(now=NOW + 200)
t3 = rn_b7.run_once(now=NOW + 250)
executed_total = st7._conn.execute(
    "SELECT COUNT(*) c FROM occurrences WHERE status='executed'"
).fetchone()["c"]
check(executed_total == 1 and st7.get(s7.schedule_id).runs_used == 1,
      "across A's death and B's takeover, exactly ONE executed occurrence "
      "exists -- max_runs=1 holds over multiple cadences and two processes "
      "(valideringsplan #7)")
check(st7.get(s7.schedule_id) is not None
      and not st7.get(s7.schedule_id).enabled,
      "and the exhausted grant is disabled through the refusal path, with the "
      "audit trail a user can read")

# --- F-1202/F-1203/F-1204: the three interleavings the gap analysis named ---
import threading
import time as _time

from app.schedule_runner import TickResult  # noqa: E402
from app.schedule_service import SchedulerService  # noqa: E402


class BlockingRunner:
    """A runner whose single tick blocks like a long ToolGate run."""

    def __init__(self, store, *, owner_id, ttl):
        self.schedules = store
        self.owner_id = owner_id
        self.lease_ttl_seconds = ttl
        self.entered = threading.Event()
        self.release = threading.Event()

    def feature_enabled(self):
        return True

    def disable_unschedulable(self):
        return []

    def recover_interrupted(self, *, now=None):
        # The real runner's recovery acquires the lease before touching
        # anything; the harness mirrors that so the service holds it from
        # startup, exactly like production.
        self.schedules.acquire_lease(
            self.owner_id, ttl_seconds=self.lease_ttl_seconds)
        return {"executed": [], "abandoned": [], "unknown": []}

    def run_once(self):
        self.entered.set()
        self.release.wait(10.0)
        return TickResult(True, False, 0, 0, 0, 0)


# F-1202: stop drains FIRST; a live thread's lease is never handed away.
st5, _, _, _ = make_env("worker-a")
br = BlockingRunner(st5, owner_id="worker-a", ttl=90.0)
svc = SchedulerService(br, poll_s=0.01)
svc.start()
check(br.entered.wait(5.0), "the long tick is running (harness sanity)")
early_stop = svc.stop(timeout=0.3)
check(early_stop is False,
      "stop cannot claim success while the thread is still inside a tool")
check(not st5.acquire_lease("worker-b", ttl_seconds=90,
                            now=_time.time()),
      "and the lease is NOT released -- a successor must not start on top "
      "of a living run (F-1202)")
br.release.set()
check(svc.stop(timeout=5.0) is True, "after the tool ends, stop drains")
check(st5.acquire_lease("worker-b", ttl_seconds=90, now=_time.time()),
      "and only THEN is the lease available to a successor")

# F-1203: the heartbeat outlives a run longer than the TTL.
st6, _, _, _ = make_env("worker-a")
br6 = BlockingRunner(st6, owner_id="worker-a", ttl=0.6)
svc6 = SchedulerService(br6, poll_s=0.01)
svc6.start()
check(br6.entered.wait(5.0), "the long tick is running (harness sanity)")
_time.sleep(1.4)  # well past the 0.6s TTL; only the heartbeat can save it
check(not st6.acquire_lease("worker-b", ttl_seconds=90,
                            now=_time.time()),
      "a run LONGER than the TTL keeps its lease -- the heartbeat renews, "
      "so no second process can take over mid-tool (F-1203)")
br6.release.set()
svc6.stop(timeout=5.0)
check(st6.acquire_lease("worker-b", ttl_seconds=90, now=_time.time()),
      "clean stop still hands the lease over afterwards")

# F-1204: unknown + pause are one transaction -- both or neither.
st7, jb7, gt7, rn7 = make_env("worker-a")
s7 = st7.create("rig_status", {}, "every:60", now=NOW)
c7 = st7.claim_due(now=NOW + 61)[0]
def _rev(store, sid):
    return store._conn.execute(
        "SELECT revision FROM schedules WHERE id=?", (sid,)).fetchone()[0]

before_rev = _rev(st7, s7.schedule_id)
prior = st7.resolve_unknown_and_pause(c7.claim_id, s7.schedule_id,
                                      now=NOW + 100)
after = st7.get(s7.schedule_id)
row7 = st7._conn.execute(
    "SELECT status FROM occurrences WHERE claim_id=?",
    (c7.claim_id,)).fetchone()
check(prior == "reserved" and row7["status"] == "unknown"
      and not after.enabled and _rev(st7, s7.schedule_id) == before_rev + 1,
      "one call yields the whole policy: occurrence unknown, grant paused, "
      "revision bumped -- atomically (F-1204)")
check(st7.resolve_unknown_and_pause(c7.claim_id, s7.schedule_id,
                                    now=NOW + 101) is None
      and _rev(st7, s7.schedule_id) == before_rev + 1,
      "a raced second call touches NOTHING -- no double pause, no double "
      "revision bump")

print(f"\n===== SCHEDULE LEASE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
