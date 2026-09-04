"""Cancellation must remain authoritative across Agent 3 execution races.

A synchronous tool cannot be physically stopped once the executor has started,
so the journal must distinguish a side effect that completed after cancellation.
Just as importantly, every stale write after executor return must lose to a
concurrent cancel: result commit, step progression, failure commit, and final
run completion.

Run: PYTHONPATH=worker python3 tests/worker_agent3_late_cancel.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading

_tmp = tempfile.mkdtemp(prefix="kaliv-late-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "a.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "s.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "j.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
os.environ["KALIV_AGENT3_DB"] = os.path.join(_tmp, "agent3.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.core import (  # noqa: E402
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    RiskClass,
    RoutePlan,
    RouteKind,
    RunState,
    Sensitivity,
    StepState,
    TurnRequest,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def make_run(run_id: str, step: AgentStep | None = None) -> AgentRun:
    return AgentRun(
        request=TurnRequest(
            "late cancel",
            mode="rig",
            tools=True,
            rag=False,
            voice=False,
            conversation_id="conv-late",
        ),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[] if step is None else [step],
        state=RunState.RUNNING,
        id=run_id,
    )


def new_store(prefix: str) -> AgentRunStore:
    temp = tempfile.mkdtemp(prefix=prefix)
    return AgentRunStore(os.path.join(temp, "agent3.db"))


# Existing physical truth contract: cancellation while the synchronous executor
# is in flight cannot undo the side effect. The run remains CANCELLED and the
# step records COMPLETED_AFTER_CANCEL with its actual result.
store = AgentRunStore(os.environ["KALIV_AGENT3_DB"])
side_effects: list[str] = []
inside = threading.Event()
release = threading.Event()


def slow_write(step):
    inside.set()
    release.wait(timeout=5)
    side_effects.append(step.tool)
    return "appended"


step = AgentStep(
    tool="note_append",
    args={"text": "x"},
    risk=RiskClass.WRITE,
    sensitivity=Sensitivity.PRIVATE,
    summary="skriv note",
)
run = make_run("r-late", step)
store.save(run)
orch = Agent3Orchestrator(store=store, executor=slow_write)

worker = threading.Thread(target=orch._execute, args=(run, step), daemon=True)
worker.start()
check(inside.wait(timeout=5), "the tool is inside the executor -- the point of no return")
orch.cancel(run.id)
check(store.load(run.id).state == RunState.CANCELLED, "cancel is recorded immediately")
release.set()
worker.join(timeout=5)
check(not worker.is_alive(), "the executor finished on its own -- cancel could not stop it")
check(side_effects == ["note_append"],
      "the side effect HAPPENED: the note was appended and no state can undo that")

fresh = store.load(run.id)
check(fresh.state == RunState.CANCELLED,
      "the run is STILL cancelled -- the late outcome did not resurrect it")
check(fresh.steps[0].state == StepState.COMPLETED_AFTER_CANCEL,
      f"the step says completed_after_cancel, not succeeded ({fresh.steps[0].state})")
check(fresh.steps[0].result == "appended",
      "and it keeps the result -- hiding it would hide what happened to the rig")
kinds = [e.get("kind") or e.get("type") for e in store.events(run.id)]
check("step_completed_after_cancel" in kinds,
      f"the timeline records the late completion explicitly ({kinds})")
check("step_succeeded" not in kinds,
      "and never claims success for something nobody wanted any more")

# Ordinary path remains ordinary.
side_effects.clear()
inside.clear()
release.set()
step2 = AgentStep(
    tool="note_append",
    args={"text": "y"},
    risk=RiskClass.WRITE,
    sensitivity=Sensitivity.PRIVATE,
    summary="skriv note",
)
run2 = make_run("r-normal", step2)
store.save(run2)
orch._execute(run2, step2)
check(store.load(run2.id).steps[0].state == StepState.SUCCEEDED,
      "an uncancelled step still succeeds normally")

# Race A: executor has returned, the first cancellation read would still have
# seen RUNNING, but cancel commits immediately before the result CAS. The stale
# success must lose, then the already-real result is merged into the cancelled
# record as COMPLETED_AFTER_CANCEL.
store_a = new_store("kaliv-late-result-race-")
step_a = AgentStep("rig_status", {}, RiskClass.READ)
run_a = make_run("r-result-race", step_a)
store_a.save(run_a)
orch_a = Agent3Orchestrator(store=store_a, executor=lambda _step: {"ok": True})
real_event_cas_a = store_a.save_with_event_if_unchanged
race_a = {"fired": False}


def cancel_before_success_commit(run_arg, **kwargs):
    if kwargs.get("kind") == "step_succeeded" and not race_a["fired"]:
        race_a["fired"] = True
        orch_a.cancel(run_arg.id)
    return real_event_cas_a(run_arg, **kwargs)


store_a.save_with_event_if_unchanged = cancel_before_success_commit  # type: ignore[method-assign]
try:
    result_a = orch_a.advance(run_a.id)
finally:
    store_a.save_with_event_if_unchanged = real_event_cas_a  # type: ignore[method-assign]
fresh_a = store_a.load(run_a.id)
kinds_a = [e["kind"] for e in store_a.events(run_a.id)]
check(race_a["fired"], "cancel is forced after executor return but before success commit")
check(result_a.state == RunState.CANCELLED and fresh_a.state == RunState.CANCELLED,
      "result-commit race preserves CANCELLED")
check(fresh_a.steps[0].state == StepState.COMPLETED_AFTER_CANCEL,
      "real executor result becomes completed_after_cancel when cancel wins result CAS")
check(fresh_a.steps[0].result == {"ok": True},
      "result is preserved even though cancellation wins")
check("step_completed_after_cancel" in kinds_a and "step_succeeded" not in kinds_a,
      "journal records late completion and no stale success event")

# Race B: success is already committed, then cancel lands before current_step is
# advanced. The step really did succeed before stop, but no future step may be
# unlocked and the stale progression write must not resurrect RUNNING.
store_b = new_store("kaliv-late-progress-race-")
step_b = AgentStep("rig_status", {}, RiskClass.READ)
run_b = make_run("r-progress-race", step_b)
store_b.save(run_b)
orch_b = Agent3Orchestrator(store=store_b, executor=lambda _step: "done")
real_plain_cas_b = store_b.save_if_unchanged
race_b = {"fired": False}


def cancel_before_progress(run_arg, **kwargs):
    if not race_b["fired"]:
        race_b["fired"] = True
        orch_b.cancel(run_arg.id)
    return real_plain_cas_b(run_arg, **kwargs)


store_b.save_if_unchanged = cancel_before_progress  # type: ignore[method-assign]
try:
    result_b = orch_b.advance(run_b.id)
finally:
    store_b.save_if_unchanged = real_plain_cas_b  # type: ignore[method-assign]
fresh_b = store_b.load(run_b.id)
kinds_b = [e["kind"] for e in store_b.events(run_b.id)]
check(race_b["fired"], "cancel is forced after success commit but before step progression")
check(result_b.state == RunState.CANCELLED and fresh_b.state == RunState.CANCELLED,
      "progression race preserves CANCELLED")
check(fresh_b.steps[0].state == StepState.SUCCEEDED,
      "step remains succeeded because success linearized before cancellation")
check(fresh_b.current_step == 0,
      "cancel prevents stale current_step progression from unlocking later work")
check("step_succeeded" in kinds_b and "run_completed" not in kinds_b,
      "journal shows success then stop, never a phantom completed run")

# Race C: all steps are done (zero-step run is the minimal case), answer
# generation finishes, then cancel lands immediately before run_completed CAS.
# Completion is another stale write and must lose just like step progression.
store_c = new_store("kaliv-late-complete-race-")
run_c = make_run("r-complete-race")
store_c.save(run_c)
orch_c = Agent3Orchestrator(store=store_c, executor=lambda _step: None,
                            answerer=lambda _run: "done")
real_event_cas_c = store_c.save_with_event_if_unchanged
race_c = {"fired": False}


def cancel_before_completed(run_arg, **kwargs):
    if kwargs.get("kind") == "run_completed" and not race_c["fired"]:
        race_c["fired"] = True
        orch_c.cancel(run_arg.id)
    return real_event_cas_c(run_arg, **kwargs)


store_c.save_with_event_if_unchanged = cancel_before_completed  # type: ignore[method-assign]
try:
    result_c = orch_c.advance(run_c.id)
finally:
    store_c.save_with_event_if_unchanged = real_event_cas_c  # type: ignore[method-assign]
fresh_c = store_c.load(run_c.id)
kinds_c = [e["kind"] for e in store_c.events(run_c.id)]
check(race_c["fired"], "cancel is forced immediately before final completion commit")
check(result_c.state == RunState.CANCELLED and fresh_c.state == RunState.CANCELLED,
      "final completion CAS cannot overwrite cancellation")
check("run_cancelled" in kinds_c and "run_completed" not in kinds_c,
      "journal records stop and never a phantom run_completed")

# Race D: an executor failure and cancellation cross at the result boundary.
# Cancellation remains the run authority, while the step truthfully records that
# the already-started executor failed after the stop won persistence.
store_d = new_store("kaliv-late-failure-race-")
step_d = AgentStep("rig_status", {}, RiskClass.READ)
run_d = make_run("r-failure-race", step_d)
store_d.save(run_d)


def exploding(_step):
    raise RuntimeError("boom")


orch_d = Agent3Orchestrator(store=store_d, executor=exploding)
real_event_cas_d = store_d.save_with_event_if_unchanged
race_d = {"fired": False}


def cancel_before_failure_commit(run_arg, **kwargs):
    if kwargs.get("kind") == "step_failed" and not race_d["fired"]:
        race_d["fired"] = True
        orch_d.cancel(run_arg.id)
    return real_event_cas_d(run_arg, **kwargs)


store_d.save_with_event_if_unchanged = cancel_before_failure_commit  # type: ignore[method-assign]
try:
    result_d = orch_d.advance(run_d.id)
finally:
    store_d.save_with_event_if_unchanged = real_event_cas_d  # type: ignore[method-assign]
fresh_d = store_d.load(run_d.id)
kinds_d = [e["kind"] for e in store_d.events(run_d.id)]
check(race_d["fired"], "cancel is forced immediately before executor failure commit")
check(result_d.state == RunState.CANCELLED and fresh_d.state == RunState.CANCELLED,
      "failure race preserves CANCELLED instead of resurrecting FAILED")
check(fresh_d.steps[0].state == StepState.FAILED and "boom" in (fresh_d.steps[0].error or ""),
      "executor failure remains visible on the cancelled step")
check("step_failed_after_cancel" in kinds_d and "step_failed" not in kinds_d,
      "journal preserves failure ordering without stale failure commit")

print(f"\n===== AGENT3 LATE CANCEL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
