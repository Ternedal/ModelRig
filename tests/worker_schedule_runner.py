"""Dormant scheduler runner integration: claim -> JobStore -> ToolGate.

Run: PYTHONPATH=worker python3 tests/worker_schedule_runner.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.jobs import JobStore  # noqa: E402
from app.schedule_runner import SchedulerRunner  # noqa: E402
from app.scheduler import ScheduleStore  # noqa: E402
from app import tools as T  # noqa: E402

passed = failed = 0
NOW = 1_000_000.0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def make_env(*, feature=True, gate_enabled=True):
    td = tempfile.mkdtemp()
    schedules = ScheduleStore(os.path.join(td, "schedules.db"))
    jobs = JobStore(os.path.join(td, "jobs.db"))
    audit = T.AuditLog(os.path.join(td, "audit.db"))
    gate = T.ToolGate(audit=audit, state_file=None)
    gate.set_enabled(gate_enabled)
    runner = SchedulerRunner(
        schedules,
        jobs,
        gate,
        feature_enabled=lambda: feature,
    )
    return schedules, jobs, gate, runner


def last_job(jobs):
    recent = jobs.recent(1)
    return recent[0] if recent else None


# --- both switches are real brakes ------------------------------------------

s, j, g, r = make_env(feature=False, gate_enabled=True)
plan = s.create("runner_read_off", {}, "every:60", now=NOW)
out = r.run_once(now=NOW + 61)
check(not out.enabled and out.claimed == 0, "feature OFF means no claim and no work")
check(s.get(plan.schedule_id).due_at == NOW + 60, "feature OFF does not consume the due occurrence")
check(j.recent() == [], "feature OFF creates no background job theatre")
s.close()

s, j, g, r = make_env(feature=True, gate_enabled=False)
plan = s.create("runner_read_gate_off", {}, "every:60", now=NOW)
out = r.run_once(now=NOW + 61)
check(out.enabled and out.paused and out.claimed == 0, "global tool kill-switch pauses before claiming")
check(s.get(plan.schedule_id).due_at == NOW + 60, "global tool pause preserves the occurrence")
check(j.recent() == [], "global tool pause creates no jobs")
s.close()

# --- read path: executes once, records truth, leaks no result into job state --

calls = []
read_name = "_runner_read_ok"
T.REGISTRY[read_name] = T.Tool(
    name=read_name,
    description="runner test read",
    risk="read",
    sensitivity="private",
    # Every tool now states whether it may run with nobody watching (F-604), and
    # the default is no. These fixtures are testing the RUNNER, so they say yes
    # deliberately rather than inheriting it -- which is the whole point of the
    # flag: delete_model and note_append are both "write", and only one of them
    # should ever fire at 03:00.
    schedulable=True,
    run=lambda args: calls.append(dict(args)) or ("PRIVATE_RESULT_" * 100),
)
try:
    s, j, g, r = make_env()
    plan = s.create(read_name, {"x": 1}, "every:60", now=NOW)
    out = r.run_once(now=NOW + 61)
    job = last_job(j)
    check(out.claimed == 1 and out.completed == 1 and out.failed == 0, "a due read executes through the runner")
    check(calls == [{"x": 1}], "the read tool receives the frozen arguments exactly once")
    check(job and job["status"] == "completed", "the JobStore reaches an honest completed terminal state")
    check("PRIVATE_RESULT" not in (job or {}).get("detail", ""), "private tool output is not copied into operational job status")
    check(s.get(plan.schedule_id).runs_used == 1, "successful execution consumes one run budget unit")
    check(r.run_once(now=NOW + 61).claimed == 0, "the same occurrence cannot execute twice")
    row = g.audit.recent(1)[0]
    check(row["tool"] == read_name and row["origin"] == "schedule" and row["outcome"] == "executed", "the read has a scheduled audit trail")
    s.close()
finally:
    T.REGISTRY.pop(read_name, None)

# --- approved write path: no card, exact approval in the audit ---------------

writes = []
write_name = "_runner_write_ok"
T.REGISTRY[write_name] = T.Tool(
    name=write_name,
    description="runner test write",
    risk="write",
    sensitivity="private",
    schedulable=True,
    run=lambda args: writes.append(dict(args)) or "written",
)
try:
    s, j, g, r = make_env()
    plan = s.create(write_name, {"text": "morgen"}, "every:60", approve_write=True, now=NOW)
    out = r.run_once(now=NOW + 61)
    check(out.completed == 1 and writes == [{"text": "morgen"}], "an exact pre-approved write runs without a confirmation card")
    row = g.audit.recent(1)[0]
    check(row["confirmation_id"] == f"schedule:{plan.approved_fingerprint[:12]}", "the audit identifies the schedule approval that authorised the write")
    check(row["origin"] == "schedule" and row["outcome"] == "executed", "the write is visibly a scheduled execution")
    s.close()
finally:
    T.REGISTRY.pop(write_name, None)

# --- permanent refusals disable the plan and leave an audit ------------------

blocked_calls = []
blocked_name = "_runner_write_mismatch"
T.REGISTRY[blocked_name] = T.Tool(
    name=blocked_name,
    description="runner mismatch write",
    risk="write",
    run=lambda args: blocked_calls.append(args) or "should not run",
)
try:
    s, j, g, r = make_env()
    plan = s.create(blocked_name, {"text": "approved"}, "every:60", approve_write=True, now=NOW)
    with s._lock:
        s._conn.execute(
            "UPDATE schedules SET args=? WHERE id=?",
            (json.dumps({"text": "changed"}), plan.schedule_id),
        )
        s._conn.commit()
    out = r.run_once(now=NOW + 61)
    job = last_job(j)
    check(out.blocked == 1 and blocked_calls == [], "changed write arguments are blocked before execution")
    check(not s.get(plan.schedule_id).enabled, "a stretched approval permanently disables the plan")
    check(job and job["status"] == "failed", "a permanent policy refusal is terminal and visible in JobStore")
    row = g.audit.recent(1)[0]
    check(row["outcome"] == "blocked" and row["origin"] == "schedule", "a pre-gate policy refusal is still audited")
    check(row["confirmation_id"] == f"schedule:{plan.approved_fingerprint[:12]}", "the blocked audit points at the stale approval")
    s.close()
finally:
    T.REGISTRY.pop(blocked_name, None)

s, j, g, r = make_env()
unknown = s.create("_runner_no_such_tool", {}, "every:60", now=NOW)
out = r.run_once(now=NOW + 61)
check(out.blocked == 1 and not s.get(unknown.schedule_id).enabled, "an unknown stored tool fails closed and disables itself")
check(last_job(j)["status"] == "failed", "unknown tool refusal is visible as a failed job")
check(g.audit.recent(1)[0]["risk"] == "unknown", "unknown tool refusal is audited without inventing a risk class")
s.close()

# Expiry and spent budget are standing approvals that have ended, not retries.
expiry_name = "_runner_expiry"
T.REGISTRY[expiry_name] = T.Tool(
    name=expiry_name, description="expiry read", risk="read", run=lambda args: "no"
)
try:
    s, j, g, r = make_env()
    expired = s.create(expiry_name, {}, "every:60", ttl_days=1, now=NOW)
    out = r.run_once(now=NOW + 2 * 86400)
    check(out.blocked == 1 and not s.get(expired.schedule_id).enabled, "an expired approval is blocked once and disabled")
    check("udløbet" in last_job(j)["detail"], "the expiry reason reaches job status")
    s.close()

    s, j, g, r = make_env()
    spent = s.create(expiry_name, {}, "every:60", max_runs=1, now=NOW)
    with s._lock:
        s._conn.execute("UPDATE schedules SET runs_used=1 WHERE id=?", (spent.schedule_id,))
        s._conn.commit()
    out = r.run_once(now=NOW + 61)
    check(out.blocked == 1 and not s.get(spent.schedule_id).enabled, "a spent run budget is blocked and disabled")
    check("budget" in last_job(j)["detail"], "the budget reason reaches job status")
    s.close()
finally:
    T.REGISTRY.pop(expiry_name, None)

# --- transient tool pause skips one occurrence but preserves the schedule ----

pause_name = "_runner_paused_tool"
# schedulable=True because this is a read the scheduler is allowed to run, and
# the test is about a GATE-disabled tool (a transient pause), not an
# unschedulable one (a permanent refusal, F-710). Before schedulability existed
# this fixture did not have to say so; now it does, exactly like the real reads.
T.REGISTRY[pause_name] = T.Tool(
    name=pause_name, description="paused read", risk="read",
    schedulable=True, run=lambda args: "no"
)
try:
    s, j, g, r = make_env()
    plan = s.create(pause_name, {}, "every:60", now=NOW)
    g.set_enabled(False, tool=pause_name)
    out = r.run_once(now=NOW + 61)
    state = s.get(plan.schedule_id)
    check(out.blocked == 1 and state.enabled, "a single disabled tool pauses rather than deleting its schedule")
    check(state.runs_used == 0 and state.due_at > NOW + 61, "the paused occurrence is skipped, not counted or immediately retried")
    check(last_job(j)["status"] == "cancelled", "a transient pause is distinguished from a permanent failure")
    check(g.audit.recent(1)[0]["outcome"] == "blocked", "the transient policy pause is audited too")
    s.close()
finally:
    T.REGISTRY.pop(pause_name, None)

# --- tool failure: no false success, schedule survives for the next cadence --

error_name = "_runner_tool_error"

def boom(args):
    raise T.ToolError("kontrolleret fejl")

T.REGISTRY[error_name] = T.Tool(
    name=error_name, description="error read", risk="read", run=boom
)
try:
    s, j, g, r = make_env()
    plan = s.create(error_name, {}, "every:60", now=NOW)
    out = r.run_once(now=NOW + 61)
    state = s.get(plan.schedule_id)
    check(out.failed == 1 and state.enabled and state.runs_used == 0, "a tool error fails the job without killing the recurring plan")
    check(last_job(j)["status"] == "failed" and "kontrolleret fejl" in last_job(j)["detail"], "the job records the real tool failure reason")
    check(g.audit.recent(1)[0]["outcome"] == "error", "ToolGate remains the audit authority for execution errors")
    s.close()
finally:
    T.REGISTRY.pop(error_name, None)

# --- a tool that may no longer run unattended does not loop forever (F-710) --
#
# ToolGate refuses an old delete_model grant every cadence. Before this, the
# occurrence claimed, blocked, and came back tomorrow -- a row from before
# schedulability existed becomes a job that fails on a loop. Two defences: the
# runner refuses it permanently so recovery stops retrying, and startup disables
# it so it does not even wake.

import json as _json  # noqa: E402

from app.scheduler import Schedule as _Sched, fingerprint as _fp  # noqa: E402

_schedules, _jobs, _gate, _runner = make_env()

# _permanent_refusal must be True for an unschedulable tool, so a claimed
# occurrence is marked dead instead of retried next cadence.
_dm = T.REGISTRY["delete_model"]
_dm_fp = _fp("delete_model", {"name": "m"})
_dm_row = _Sched("dm", "delete_model", {"name": "m"}, "daily:03:00", _dm_fp,
                 9e18, 0, 0, 0, 0, True)
check(SchedulerRunner._permanent_refusal(_dm_row, _dm, _dm_fp, now=1.0) is True,
      "an unschedulable tool is a PERMANENT refusal -- the occurrence dies "
      "instead of blocking on a loop every cadence")

_rs = T.REGISTRY["rig_status"]
_rs_row = _Sched("rs", "rig_status", {}, "daily:03:00", None, 9e18, 0, 0, 0, 0, True)
check(SchedulerRunner._permanent_refusal(_rs_row, _rs, _fp("rig_status", {}), now=1.0) is False,
      "and a schedulable read is not permanently refused -- the brake is "
      "specific, not a blanket stop")

# startup migration disables legacy unschedulable rows, idempotently.
_schedules.create("rig_status", {}, "daily:03:00", now=1.0)
_schedules._conn.execute(
    "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"
    " expires_at, max_runs, runs_used, due_at, missed, enabled, created)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
    ("legacy", "delete_model", _json.dumps({"name": "m"}), "daily:03:00", _dm_fp,
     9e18, 0, 0, 0, 0, 1.0))
_schedules._conn.commit()

_migrated = _runner.disable_unschedulable()
check(_migrated == ["legacy"],
      "startup disables the legacy delete_model grant so it never wakes")
_state = {s.schedule_id: s.enabled for s in _schedules.list_all()}
check(_state["legacy"] is False, "the legacy row is disabled")
check(any(sid != "legacy" and en for sid, en in _state.items()),
      "the valid rig_status grant is left enabled")
check(_runner.disable_unschedulable() == [],
      "running the migration again disables nothing -- it is idempotent, so "
      "every startup is safe")

# An unknown tool -- one removed from the registry entirely -- is disabled too,
# because it cannot run either and would otherwise fail on a loop.
_schedules._conn.execute(
    "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"
    " expires_at, max_runs, runs_used, due_at, missed, enabled, created)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
    ("ghost", "tool_that_was_deleted", "{}", "daily:03:00", None,
     9e18, 0, 0, 0, 0, 1.0))
_schedules._conn.commit()
check(_runner.disable_unschedulable() == ["ghost"],
      "a grant for a tool no longer in the registry is disabled too")

print(f"\n===== SCHEDULE RUNNER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
