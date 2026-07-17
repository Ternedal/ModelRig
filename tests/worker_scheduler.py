"""Scheduler policy, cadence math, and persistent claim truth."""
from __future__ import annotations

import os
import sys
import tempfile
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


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except S.ScheduleError as e:
        return str(e)


os.environ.pop("KALIV_SCHEDULER", None)
check(not S.enabled(), "the scheduler is OFF unless Anders turns it on")
os.environ["KALIV_SCHEDULER"] = "1"
check(S.enabled(), "the flag turns it on")
os.environ.pop("KALIV_SCHEDULER", None)

check(S.parse_cadence("every:900") == S.Cadence("every", seconds=900), "every:900 parses")
check(S.parse_cadence("daily:03:00") == S.Cadence("daily", hour=3, minute=0), "daily:03:00 parses")
msg = raises(S.parse_cadence, "every:5")
check(msg is not None and "minimum" in msg, "too-fast intervals are refused")
for bad in ("", "hourly", "daily:24:00", "daily:3:00", "every:-1", "cron:* * * * *"):
    check(raises(S.parse_cadence, bad) is not None, f"{bad!r} is refused, not guessed at")

base = time.mktime((2026, 7, 17, 10, 0, 0, 0, 0, -1))
check(S.next_run(S.Cadence("every", seconds=900), base) == base + 900, "interval fires 900s later")
nxt = S.next_run(S.Cadence("daily", hour=3, minute=0), base)
lt = time.localtime(nxt)
check((lt.tm_hour, lt.tm_min) == (3, 0) and nxt > base, "daily 03:00 chooses the next real occurrence")
early = time.mktime((2026, 7, 17, 1, 0, 0, 0, 0, -1))
nxt2 = S.next_run(S.Cadence("daily", hour=3, minute=0), early)
check(time.localtime(nxt2).tm_mday == 17 and nxt2 - early == 7200, "daily 03:00 before dawn chooses the same day")
check(raises(S.next_run, S.Cadence("mystery"), base) is not None, "unknown cadence kinds fail closed")

cad = S.Cadence("daily", hour=3, minute=0)
due = time.mktime((2026, 7, 10, 3, 0, 0, 0, 0, -1))
now = time.mktime((2026, 7, 17, 10, 0, 0, 0, 0, -1))
missed, next_due = S.catch_up(cad, due, now)
check(missed == 7, "a week offline reports seven misses and one current occurrence")
check(next_due > now, "catch-up advances into the future")
missed0, due0 = S.catch_up(cad, now + 3600, now)
check(missed0 == 0 and due0 == now + 3600, "a not-yet-due task is left unchanged")
year = 365 * 24 * 3600
m_year, due_year = S.catch_up(S.Cadence("every", seconds=60), base + 60, base + year)
check(m_year == year // 60 - 1 and due_year == base + year + 60, "long interval catch-up is exact without replaying timestamps")

fp = S.fingerprint("note_append", {"text": "morgenlog"})
check(S.refusal("read", None, fp) is None, "reads need no prior approval")
check("kl. 03:00" in (S.refusal("write", None, fp) or ""), "unapproved writes are refused")
check(S.refusal("write", fp, fp) is None, "the exact approved write may run")
check("ændret" in (S.refusal("write", fp, S.fingerprint("note_append", {"text": "other"})) or ""), "argument changes void approval")
desktop_why = S.refusal("desktop", fp, fp)
check(desktop_why is not None, "desktop actions can never be scheduled")
check("screenshot-bindingen" in (desktop_why or ""), "desktop refusal explains why stale screenshots cannot authorise clicks")
check(S.refusal("mystery", None, fp) is not None, "unknown risk fails closed")
check(S.fingerprint("t", {"a": 1, "b": 2}) == S.fingerprint("t", {"b": 2, "a": 1}), "argument order does not change approval identity")
check(S.fingerprint("t", {"a": 1}) != S.fingerprint("t", {"a": "1"}), "numeric and string arguments have different approval identities")
check(S.fingerprint("t1", {"a": 1}) != S.fingerprint("t2", {"a": 1}), "the same args on another tool need another approval")

with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "schedules.db")
    st = S.ScheduleStore(path)

    read_id = st.create(tool="rig_status", args={}, cadence="every:60", risk="read", now=base)
    read = st.get(read_id)
    check(read is not None and read["next_due"] == base + 60, "create persists a future first due time")
    check(read["args"] == {} and read["enabled"], "stored args round-trip and schedule starts enabled")

    check(raises(st.create, tool="note_append", args={"text": "x"}, cadence="daily:03:00", risk="write", now=base) is not None, "write schedule without approval is not stored")
    check(raises(st.create, tool="note_append", args={"text": "x"}, cadence="daily:03:00", risk="write", approved_fingerprint="wrong", now=base) is not None, "mismatched write approval is not stored")
    write_args = {"text": "x"}
    write_fp = S.fingerprint("note_append", write_args)
    write_id = st.create(tool="note_append", args=write_args, cadence="daily:03:00", risk="write", approved_fingerprint=write_fp, now=base)
    check(st.get(write_id)["approved_fingerprint"] == write_fp, "exact write approval is frozen with the record")
    check(raises(st.create, tool="click", args={}, cadence="every:60", risk="desktop", approved_fingerprint=S.fingerprint("click", {}), now=base) is not None, "desktop schedule is refused at creation")

    st.close()
    st = S.ScheduleStore(path)
    check(st.get(read_id) is not None and st.get(write_id) is not None, "schedules survive a store restart")

    first = st.claim_due(base + 190)
    claimed = [x for x in first if x["id"] == read_id]
    check(len(claimed) == 1, "a due schedule is claimed once")
    check(claimed[0]["missed_this_claim"] == 2, "two earlier interval occurrences are reported as missed")
    check(claimed[0]["next_due"] == base + 240, "claim advances next_due past now")
    check(not [x for x in st.claim_due(base + 190) if x["id"] == read_id], "the same occurrence cannot be claimed twice")

    st2 = S.ScheduleStore(path)
    check(not [x for x in st2.claim_due(base + 190) if x["id"] == read_id], "a second process/store cannot double-claim")
    st2.close()

    check(st.set_enabled(read_id, False, now=base + 200), "schedule can be disabled without deletion")
    check(not st.get(read_id)["enabled"], "disabled state persists")
    check(st.set_enabled(read_id, True, now=base + 1000), "schedule can be explicitly re-enabled")
    check(st.get(read_id)["next_due"] == base + 1060, "re-enable starts in the future instead of replaying backlog")

    long_result = "x" * 5000
    check(st.complete(read_id, long_result, now=base + 1001), "latest execution result can be recorded")
    check(len(st.get(read_id)["last_result"]) == 4000, "stored result is bounded")
    check(st.delete(write_id) and st.get(write_id) is None, "delete removes only the selected schedule")
    st.close()

print(f"\n===== SCHEDULER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
