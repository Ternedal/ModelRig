"""Scheduler policy and cadence math.

The interesting part is not cron -- it is what a task may do at 03:00 when
there is nobody to approve it.

Run: PYTHONPATH=worker python3 tests/worker_scheduler.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import scheduler as S  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def raises(fn, *a):
    try:
        fn(*a)
        return None
    except S.ScheduleError as e:
        return str(e)


# --- dormant by default -----------------------------------------------------

os.environ.pop("KALIV_SCHEDULER", None)
check(not S.enabled(), "the scheduler is OFF unless Anders turns it on")
os.environ["KALIV_SCHEDULER"] = "1"
check(S.enabled(), "the flag turns it on")
os.environ.pop("KALIV_SCHEDULER", None)

# --- cadence ----------------------------------------------------------------

check(S.parse_cadence("every:900") == S.Cadence("every", seconds=900), "every:900 parses")
check(S.parse_cadence("daily:03:00") == S.Cadence("daily", hour=3, minute=0), "daily:03:00 parses")

msg = raises(S.parse_cadence, "every:5")
check(msg is not None and "minimum" in msg,
      "a 5-second schedule is refused -- that is a busy loop wearing a calendar's clothes")
for bad in ("", "hourly", "daily:24:00", "daily:3:00", "every:-1", "cron:* * * * *"):
    check(raises(S.parse_cadence, bad) is not None, f"{bad!r} is refused, not guessed at")

# --- next_run ---------------------------------------------------------------

base = time.mktime((2026, 7, 17, 10, 0, 0, 0, 0, -1))
check(S.next_run(S.Cadence("every", seconds=900), base) == base + 900, "interval fires 900s later")

nxt = S.next_run(S.Cadence("daily", hour=3, minute=0), base)
lt = time.localtime(nxt)
check((lt.tm_hour, lt.tm_min) == (3, 0) and nxt > base,
      "daily:03:00 from 10:00 fires at 03:00 -- tomorrow, not in the past")

early = time.mktime((2026, 7, 17, 1, 0, 0, 0, 0, -1))
nxt2 = S.next_run(S.Cadence("daily", hour=3, minute=0), early)
check(time.localtime(nxt2).tm_mday == 17 and nxt2 - early == 7200,
      "daily:03:00 from 01:00 fires the SAME day, two hours later")

# --- the rig was off: missed runs are reported, never replayed --------------

cad = S.Cadence("daily", hour=3, minute=0)
due = time.mktime((2026, 7, 10, 3, 0, 0, 0, 0, -1))
now = time.mktime((2026, 7, 17, 10, 0, 0, 0, 0, -1))
missed, next_due = S.catch_up(cad, due, now)
# 10/7 03:00 through 17/7 03:00 inclusive is EIGHT fire times, not seven: one
# fires now, seven were missed. My first expectation here said six, and the
# arithmetic was wrong, not the code -- which is the entire reason to compute
# this instead of eyeballing it at 03:00.
check(missed == 7,
      f"a week offline reports 7 missed runs and runs ONCE now -- not eight times ({missed})")
check(next_due > now, "the next due time is in the future, not backfilled")

missed0, due0 = S.catch_up(cad, now + 3600, now)
check(missed0 == 0 and due0 == now + 3600, "a task that is not due yet is left alone")

# --- the 03:00 question: what may actually run ------------------------------

fp = S.fingerprint("note_append", {"text": "morgenlog"})

check(S.refusal("read", None, fp) is None,
      "a scheduled READ runs unattended -- nothing to approve")

why = S.refusal("write", None, fp)
check(why is not None and "kl. 03:00" in why,
      "a scheduled WRITE with no prior approval is refused, and says why")

check(S.refusal("write", fp, fp) is None,
      "a write Anders approved at schedule time DOES run: that approval is real")

other = S.fingerprint("note_append", {"text": "noget helt andet"})
why = S.refusal("write", fp, other)
check(why is not None and "ændret" in why,
      "changing the arguments VOIDS the approval -- he approved that action, not this one")

why = S.refusal("desktop", fp, fp)
check(why is not None and "03:00" in why,
      "a desktop action can NEVER be scheduled, approval or not")
check("screenshot-bindingen" in (why or ""),
      "and the refusal explains why binding cannot save it: that screen is gone")

# --- the fingerprint is about meaning, not spelling -------------------------

check(S.fingerprint("t", {"a": 1, "b": 2}) == S.fingerprint("t", {"b": 2, "a": 1}),
      "argument ORDER does not change the fingerprint")
check(S.fingerprint("t", {"a": 1}) != S.fingerprint("t", {"a": "1"}),
      "1 and \"1\" are different arguments and must not share an approval")
check(S.fingerprint("t1", {"a": 1}) != S.fingerprint("t2", {"a": 1}),
      "the same args on a different TOOL is a different approval")

# --- the standing grant: what "approve once" must NOT mean ------------------
# This is the part of "approve once, at creation, with the arguments frozen"
# that needed a second look. Once means forever unless something says otherwise.

fp_ok = S.fingerprint("note_append", {"text": "morgenlog"})
NOW = 1_000_000.0

check(S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW + 10) is None,
      "an approval inside its horizon runs")
why = S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW - 1)
check(why is not None and "udløbet" in why,
      "an EXPIRED approval refuses -- a yes from March is not a yes in July")
check("igen" in (why or ""), "and it says how to renew: ask again, deliberately")

why = S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW + 10,
                runs_used=5, max_runs=5)
check(why is not None and "budget" in why,
      "a spent run budget refuses -- 'every morning' does not mean 'forever mornings'")
check(S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW + 10,
                runs_used=4, max_runs=5) is None, "an unspent budget runs")
check(S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW + 10,
                runs_used=9999, max_runs=0) is None,
      "max_runs=0 means no budget -- the TTL alone bounds it")

# The kill-switch must reach the one caller Anders cannot see.
why = S.refusal("read", None, fp_ok, now=NOW, expires_at=NOW + 10, tools_enabled=False)
check(why is not None and "slået fra" in why,
      "the kill-switch stops scheduled READS too -- background work is exactly what must stop")
why = S.refusal("write", fp_ok, fp_ok, now=NOW, expires_at=NOW + 10, tool_disabled=True)
check(why is not None and "venter" in why,
      "a disabled single tool pauses its schedule rather than failing it")

# --- the store: where the approval is actually captured ---------------------

import tempfile  # noqa: E402

store = S.ScheduleStore(os.path.join(tempfile.mkdtemp(), "s.db"))

sched = store.create("rig_status", {}, "every:900", now=NOW)
check(sched.approved_fingerprint is None,
      "a READ schedule stores no write-approval: there was nothing to approve")
check(sched.expires_at == NOW + S.DEFAULT_TTL_DAYS * 86400,
      "every schedule gets an expiry, even when nobody asked for one")
check(sched.due_at == NOW + 900, "the first run is one interval away, not immediately")

w = store.create("note_append", {"text": "morgenlog"}, "daily:03:00",
                 approve_write=True, max_runs=30, now=NOW)
check(w.approved_fingerprint == S.fingerprint("note_append", {"text": "morgenlog"}),
      "the approval is stored as a fingerprint of the exact action")
check(S.refusal("write", w.approved_fingerprint,
                S.fingerprint("note_append", {"text": "noget andet"}),
                now=NOW, expires_at=w.expires_at) is not None,
      "the stored approval cannot be stretched to a different action later")

check(raises(store.create, "x", {}, "every:5") is not None,
      "a bad cadence is refused BEFORE anything is written to disk")
check(len(store.list_all()) == 2, "the refused schedule left no trace")

try:
    store.create("x", {}, "every:900", ttl_days=0, now=NOW)
    check(False, "a schedule without an expiry must be refused")
except S.ScheduleError as e:
    check("hele pointen" in str(e), "an immortal schedule is refused on principle")

# --- restart and progress ---------------------------------------------------

after = store.record_run(sched.schedule_id, ran=True, now=NOW + 901)
check(after.runs_used == 1, "a run is counted")
check(after.due_at > NOW + 901, "the next run is scheduled forward, never in the past")

# A week offline: the store records what was missed, and does not replay it.
gone = store.record_run(sched.schedule_id, ran=True, now=NOW + 901 + 7 * 86400)
check(gone.missed > 0, f"time offline is recorded as missed runs ({gone.missed})")
check(gone.runs_used == 2, "and the missed ones are NOT executed -- runs_used moved by one")

reopened = S.ScheduleStore(store.path)
check(len(reopened.list_all()) == 2, "schedules survive a restart -- that is when they matter")
check(reopened.get(w.schedule_id).approved_fingerprint == w.approved_fingerprint,
      "and so does the approval they were created with")

store.set_enabled(sched.schedule_id, False)
due_ids = [d.schedule_id for d in store.due(now=NOW + 10**6)]
check(sched.schedule_id not in due_ids, "a disabled schedule is never due")
check(w.schedule_id in due_ids, "...and disabling one does not disable the others")
check(store.delete(w.schedule_id) and store.get(w.schedule_id) is None, "a schedule can be deleted")

print(f"\n===== SCHEDULER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
