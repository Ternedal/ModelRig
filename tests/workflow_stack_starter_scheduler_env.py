#!/usr/bin/env python3
"""The stack starter's scheduler env block must survive edits around it.

#785 spliced a task-ui line into the middle of the scheduler here-string
assignment. The result parsed fine -- PowerShell happily chains
``$schedulerEnv = $taskUiEnv = ...`` across a line break -- but with
-EnableScheduler the worker cmd silently lost KALIV_SCHEDULER, every DB
path and the approval secret. No parser or encoding gate can see that;
only the SHAPE of the file can.

This gate pins the shape: both scheduler branches assign a here-string to
$schedulerEnv, the enabled branch's here-string carries every scheduler
key, and $taskUiEnv is defined once, before -- not inside -- the scheduler
branches.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"

REQUIRED_SCHEDULER_KEYS = (
    "KALIV_SCHEDULER=",
    "KALIV_SCHEDULER_POLL_S=",
    "KALIV_SCHEDULES_DB=",
    "MODELRIG_JOBS_DB=",
    "KALIV_AUDIT_DB=",
    "KALIV_TOOLS_STATE=",
    "KALIV_TOOLS_DIR=",
    "KALIV_SCHEDULER_APPROVAL_SECRET=",
)

FAILED = 0


def check(ok: bool, message: str) -> None:
    global FAILED
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if not ok:
        FAILED = 1


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    # Self-test: the spliced shape from #785 must be detectable.
    spliced = '$schedulerEnv = # comment\n$taskUiEnv = if ($x) { "a" } else { "" }\n@"\nset "KALIV_SCHEDULER=1"\n"@'
    check(
        re.search(r'\$schedulerEnv = @"', spliced) is None,
        "self-test: a spliced assignment no longer reads as a here-string assignment",
    )

    assignments = re.findall(r'^\s*\$schedulerEnv = @"', text, re.M)
    check(len(assignments) == 2, f"both scheduler branches assign a here-string ({len(assignments)} of 2)")

    check(
        re.search(r'^\s*\$schedulerEnv = #', text, re.M) is None,
        "no scheduler assignment is cut off by a comment",
    )

    enabled = re.search(r'if \(\$EnableScheduler\) \{(.*?)\n\}\s*\nelse', text, re.S)
    check(enabled is not None, "the enabled scheduler branch is found")
    body = enabled.group(1) if enabled else ""
    for key in REQUIRED_SCHEDULER_KEYS:
        check(f'set "{key}' in body, f"enabled branch writes {key}")

    task_ui_defs = [m.start() for m in re.finditer(r"^\$taskUiEnv = ", text, re.M)]
    # The branch, not the inline ternary on the $schedulerValue line: the
    # block starts at column 0 and ends the line.
    branch = re.search(r"^if \(\$EnableScheduler\) \{\s*$", text, re.M)
    branch_start = branch.start() if branch else -1
    check(len(task_ui_defs) == 1, f"$taskUiEnv is defined exactly once ({len(task_ui_defs)})")
    check(
        bool(task_ui_defs) and branch_start > 0 and task_ui_defs[0] < branch_start,
        "$taskUiEnv is defined before the scheduler branches, not inside them",
    )
    check(text.count("$taskUiEnv\n") >= 2, "both generated cmd files emit $taskUiEnv")

    print("stack starter scheduler env: " + ("OK" if not FAILED else "SHAPE BROKEN"))
    return FAILED


if __name__ == "__main__":
    sys.exit(main())
