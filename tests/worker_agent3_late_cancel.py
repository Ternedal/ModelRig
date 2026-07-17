"""Cancelling a run cannot stop a synchronous tool already inside the executor.

F-308. Agent 3's executor has no cancellation handle, so cancel() cannot reach
into a slow write. Two consequences, and the second one is the dangerous one:

  1. The side effect happens anyway. You cannot un-append a note or un-delete a
     model. Reporting "cancelled" alone describes a rig that does not exist.
  2. cancel() loads its OWN copy of the run, sets CANCELLED and saves. _execute
     is holding a copy from before that, still saying RUNNING -- so its save
     wrote the cancellation back out of existence, and the step said
     "succeeded". The user pressed stop; the record forgot.

The fix is not to pretend we can cancel. It is to tell the truth: the run stays
CANCELLED, and the step says completed_after_cancel with its result, so the
timeline shows what actually happened to the machine.

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


store = AgentRunStore(os.environ["KALIV_AGENT3_DB"])

# A tool that takes long enough for a human to press stop, and that really does
# something to the machine while it runs.
side_effects: list[str] = []
inside = threading.Event()
release = threading.Event()


def slow_write(step):
    inside.set()
    release.wait(timeout=5)
    side_effects.append(step.tool)      # the note is appended. it is appended.
    return "appended"


def make_run(run_id: str, step: AgentStep) -> AgentRun:
    return AgentRun(
        request=TurnRequest("late cancel", mode="rig", tools=True, rag=False,
                            voice=False, conversation_id="conv-late"),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", uses_cloud=False,
                        uses_rig=True, uses_tools=True, uses_rag=False),
        steps=[step], state=RunState.RUNNING, id=run_id,
    )


step = AgentStep(tool="note_append", args={"text": "x"}, risk=RiskClass.WRITE,
                 sensitivity=Sensitivity.PRIVATE, summary="skriv note")
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
      "the run is STILL cancelled -- the late save did not resurrect it "
      "(before F-308 this said running/completed and the stop vanished)")
check(fresh.steps[0].state == StepState.COMPLETED_AFTER_CANCEL,
      f"the step says completed_after_cancel, not succeeded ({fresh.steps[0].state})")
check(fresh.steps[0].result == "appended",
      "and it keeps the result -- hiding it would hide what happened to the rig")

kinds = [e.get("kind") or e.get("type") for e in store.events(run.id)]
check("step_completed_after_cancel" in kinds,
      f"the timeline records the late completion explicitly ({kinds})")
check("step_succeeded" not in kinds,
      "and never claims success for something nobody wanted any more")

# The ordinary path must be untouched: no cancel, no drama.
side_effects.clear(); inside.clear(); release.set()
step2 = AgentStep(tool="note_append", args={"text": "y"}, risk=RiskClass.WRITE,
                  sensitivity=Sensitivity.PRIVATE, summary="skriv note")
run2 = make_run("r-normal", step2)
store.save(run2)
orch._execute(run2, step2)
check(store.load(run2.id).steps[0].state == StepState.SUCCEEDED,
      "an uncancelled step still succeeds normally")

print(f"\n===== AGENT3 LATE CANCEL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
