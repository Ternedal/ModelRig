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

print(f"\n===== SCHEDULER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
