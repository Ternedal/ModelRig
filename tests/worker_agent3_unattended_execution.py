#!/usr/bin/env python3
"""The refusal that stops a destructive tool running at 03:00 (F-604).

This exists because a mutation found nothing. Deleting the tool gate's
`if not tool.schedulable: raise`, and ScheduleAdmin's preview refusal, left all
84 suites green. Both are the fix I shipped this morning for a P1 -- a schedule
that would have deleted an Ollama model on a recurring basis with nobody awake
and no confirmation card.

I proved both by hand during the session, watched them refuse, and shipped. The
demonstration was not a test: it evaporated when the session ended, and the code
it vouched for stayed. That is the same move as writing "the rest is fixed too"
in a commit message, one layer down.

The gate is the backstop and must hold whatever the UI does. ScheduleAdmin is
where the decision is made and must refuse there, or the user believes they
scheduled something that fails silently months later. Both are asserted here,
because a defence with no test is a defence with a deadline.
"""
from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "worker"))

_TMP = tempfile.mkdtemp(prefix="kaliv-unattended-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_TMP, "audit.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_TMP, "state.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_TMP, "jobs.db"))
os.environ.setdefault("KALIV_SCHEDULE_DB", os.path.join(_TMP, "schedules.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _TMP)
os.environ.setdefault("MODELRIG_DB", os.path.join(_TMP, "rag.db"))

from app.scheduler import fingerprint  # noqa: E402
from app.tools import GATE, REGISTRY, ToolDenied  # noqa: E402

passed = 0
failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


GATE.enabled = True

# --- the gate: what actually runs at 03:00 ---------------------------------
#
# A schedule fires by handing the gate a pre-approval fingerprint. The gate used
# to check one thing -- `if tool.risk == "desktop"` -- and delete_model is
# risk=write, exactly like note_append. So the approval was honoured and the
# model was gone.

for name, args in (
    ("delete_model", {"name": "qwen3:14b"}),
    ("pull_model", {"name": "llama3.2:1b"}),
    ("cancel_job", {"job_id": "abc123"}),
):
    tool = REGISTRY[name]
    try:
        GATE.propose(name, args, conversation_id="c1", origin="schedule",
                     pre_approved=fingerprint(name, args))
        check(False, f"{name} RAN UNATTENDED with a valid pre-approval")
    except ToolDenied as exc:
        check("kan ikke køre planlagt" in str(exc),
              f"{name} is refused at the gate even with a matching approval")
        # The refusal has to be actionable. "Denied" tells a person nothing they
        # can do anything about at three in the morning.
        check(tool.unschedulable_because and tool.unschedulable_because in str(exc),
              f"{name}'s refusal says why, in words a person can act on")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name} raised {type(exc).__name__} instead of refusing: {exc}")

# A policy that blocks everything is not a policy -- it is an outage. The tool
# the scheduler exists FOR must still run.
try:
    GATE.propose("note_append", {"text": "dagens note"}, conversation_id="c1",
                 origin="schedule", pre_approved=fingerprint("note_append", {"text": "dagens note"}))
    check(True, "note_append still runs unattended -- the scheduler has a purpose")
except Exception as exc:  # noqa: BLE001
    check(False, f"note_append was refused: {exc}")

# The refusal must be recorded. A write that was stopped at 03:00 is exactly the
# event nobody witnesses, so the trail is the only witness there is.
recent = GATE.audit.recent(limit=50)
blocked = [r for r in recent
           if r.get("tool") == "delete_model" and r.get("outcome") == "blocked"]
check(bool(blocked), "the refused scheduled deletion is in the audit trail")
if blocked:
    check(blocked[0].get("origin") == "schedule",
          "and the trail says it came from a schedule, not from a person")

# --- ScheduleAdmin: where the decision is made ------------------------------
#
# The gate refusing at 03:00 is correct and insufficient. If the UI offers the
# plan, the user believes it exists, and it fails silently months later at three
# in the morning. A refusal is worth most where the decision is made.

from app.schedule_admin import ScheduleAdmin, ScheduleAdminError  # noqa: E402

admin = ScheduleAdmin()
for name, args in (("delete_model", {"name": "qwen3:14b"}), ("pull_model", {"name": "x"})):
    try:
        admin.preview(name, args, "daily:03:00")
        check(False, f"{name} could be PREVIEWED as a schedule")
    except ScheduleAdminError as exc:
        check("kan ikke planlægges" in str(exc),
              f"{name} is refused at preview, where the person is still awake")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name} preview raised {type(exc).__name__}: {exc}")

try:
    admin.preview("note_append", {"text": "x"}, "daily:03:00")
    check(True, "note_append can still be previewed")
except Exception as exc:  # noqa: BLE001
    check(False, f"note_append preview was refused: {exc}")

# --- the two must not drift apart ------------------------------------------
#
# The gate and the admin read the same field. If a future refactor teaches one
# of them a different question -- which is exactly what happened, the gate asked
# about desktop while the graph knew about destructive -- this fails.

for name, tool in sorted(REGISTRY.items()):
    if tool.schedulable:
        continue
    gate_refused = False
    try:
        GATE.propose(name, {}, conversation_id="c2", origin="schedule",
                     pre_approved=fingerprint(name, {}))
    except ToolDenied as exc:
        gate_refused = "kan ikke køre planlagt" in str(exc)
    except Exception:  # noqa: BLE001
        gate_refused = True  # refused for some other reason; still refused
    admin_refused = False
    try:
        admin.preview(name, {}, "daily:03:00")
    except ScheduleAdminError:
        admin_refused = True
    except Exception:  # noqa: BLE001
        admin_refused = True
    check(gate_refused and admin_refused,
          f"{name}: refused at BOTH the preview and the gate"
          if gate_refused and admin_refused
          else f"{name}: preview_refused={admin_refused} gate_refused={gate_refused} "
               "-- one of them has stopped asking")

print(f"\n===== UNATTENDED EXECUTION: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
