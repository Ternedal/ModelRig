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
