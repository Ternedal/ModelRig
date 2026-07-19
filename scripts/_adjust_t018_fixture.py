#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/worker_scheduler_single_flight.py")
text = path.read_text(encoding="utf-8")
replacements = {
    'second = schedules.create(tool_name, {"n": 2}, "every:60", now=NOW)':
        'second = schedules.create(tool_name, {"n": 2}, "every:60", now=NOW + 1)',
    'now=NOW + 61,\n                limit=2,':
        'now=NOW + 62,\n                limit=2,',
    'len(schedules.due(now=NOW + 61)) == 1,':
        'len(schedules.due(now=NOW + 62)) == 1,',
    'competing = runner.run_once(now=NOW + 61, limit=1)':
        'competing = runner.run_once(now=NOW + 62, limit=1)',
    'later = runner.run_once(now=NOW + 61, limit=1)':
        'later = runner.run_once(now=NOW + 62, limit=1)',
}
for old, new in replacements.items():
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"missing fixture anchor: {old!r}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")

# The old revocation test intentionally proved that a preclaimed batch rechecks
# B after A pauses it. T-018 removes the preclaim itself, which is the stronger
# invariant: after A pauses B, B must remain unclaimed and spend no budget.
path = Path("tests/worker_schedule_revoke.py")
text = path.read_text(encoding="utf-8")
old = '''    tick = rn.run_once(now=NOW + 61)
    check(tick.claimed == 2 and tick.completed == 1 and tick.blocked == 1,
          "one tick: A executes (and pauses B); B's already-claimed occurrence "
          "is cancelled instead of running against the user's pause")
    check(_runs_used(st, b.schedule_id) == 0,
          "B's reserved slot is refunded in the same tick")'''
new = '''    tick = rn.run_once(now=NOW + 61)
    check(tick.claimed == 1 and tick.completed == 1 and tick.blocked == 0,
          "one tick: A executes and pauses B before the single-flight runner "
          "attempts another durable claim")
    check(_runs_used(st, b.schedule_id) == 0,
          "B is never reserved, so its budget remains untouched")
    check(not any(
              row["schedule_id"] == b.schedule_id
              for row in st.reserved_occurrences()),
          "B has no in-flight occurrence after A pauses it")'''
if text.count(old) != 1:
    raise SystemExit(f"revocation contract target count is {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8")
