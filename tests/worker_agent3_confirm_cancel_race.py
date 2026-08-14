from __future__ import annotations

import os
import tempfile

from app.agent3.core import (
    Agent3Orchestrator,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    ConfirmationError,
    RiskClass,
    RunState,
    TurnRequest,
)


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_waiting_run(orch, caps, label):
    return orch.start_with_steps(
        TurnRequest(label, mode="rig", tools=True),
        caps,
        [AgentStep("write_once", {"label": label}, RiskClass.WRITE)],
    )


_tmp = tempfile.mkdtemp(prefix="kaliv-agent3-confirm-race-")
store = AgentRunStore(os.path.join(_tmp, "agent3.db"))
executed = []


def executor(step):
    executed.append((step.tool, dict(step.args)))
    return {"ok": True}


orch = Agent3Orchestrator(store=store, executor=executor, confirmation_ttl_seconds=30)
caps = CapabilitySnapshot(
    rig_reachable=True,
    worker_ready=True,
    tools_ready=True,
    cloud_ready=False,
    rag_ready=False,
)

# Race 1: cancel lands after confirm() has validated its stale WAITING copy but
# before the approval write. The approval CAS must lose; no stale RUNNING state
# may resurrect the cancellation.
run = make_waiting_run(orch, caps, "cancel-before-approval-commit")
check(run.state == RunState.WAITING_CONFIRMATION, "write starts at confirmation boundary")
step = run.steps[0]
real_cas = store.save_with_event_if_unchanged
race1_fired = {"value": False}


def cancel_before_approval(run_arg, **kwargs):
    if kwargs.get("kind") == "confirmation_approved" and not race1_fired["value"]:
        race1_fired["value"] = True
        orch.cancel(run_arg.id)
    return real_cas(run_arg, **kwargs)


store.save_with_event_if_unchanged = cancel_before_approval  # type: ignore[method-assign]
try:
    try:
        orch.confirm(run.id, step.id, "approve", step.confirmation_digest)
        race1_blocked = False
    except ConfirmationError:
        race1_blocked = True
finally:
    store.save_with_event_if_unchanged = real_cas  # type: ignore[method-assign]

fresh = store.load(run.id)
check(race1_fired["value"], "cancel is forced between confirmation validation and approval commit")
check(race1_blocked, "stale approval loses the compare-and-swap")
check(fresh is not None and fresh.state == RunState.CANCELLED, "cancelled state survives stale approval")
check(executed == [], "race before approval never executes the write")
kinds = [event["kind"] for event in store.events(run.id)]
check("run_cancelled" in kinds and "confirmation_approved" not in kinds,
      "audit records cancel but no phantom approval")

# Race 2: approval commits first, then cancel lands after advance() has loaded
# RUNNING/APPROVED but immediately before step_started. The execution-start CAS
# is the side-effect linearization point: cancel before it means the tool must
# never run.
run2 = make_waiting_run(orch, caps, "cancel-before-step-start")
step2 = run2.steps[0]
race2_fired = {"value": False}


def cancel_before_step_started(run_arg, **kwargs):
    if kwargs.get("kind") == "step_started" and not race2_fired["value"]:
        race2_fired["value"] = True
        orch.cancel(run_arg.id)
    return real_cas(run_arg, **kwargs)


store.save_with_event_if_unchanged = cancel_before_step_started  # type: ignore[method-assign]
try:
    result2 = orch.confirm(run2.id, step2.id, "approve", step2.confirmation_digest)
finally:
    store.save_with_event_if_unchanged = real_cas  # type: ignore[method-assign]

fresh2 = store.load(run2.id)
check(race2_fired["value"], "cancel is forced immediately before execution start")
check(result2.state == RunState.CANCELLED, "advance returns cancelled when execution-start CAS loses")
check(fresh2 is not None and fresh2.state == RunState.CANCELLED, "persisted run remains cancelled")
check(executed == [], "cancel before step_started prevents the side effect")
kinds2 = [event["kind"] for event in store.events(run2.id)]
check("confirmation_approved" in kinds2, "audit records approval that happened before cancel")
check("run_cancelled" in kinds2, "audit records the later cancel")
check("step_started" not in kinds2, "audit never claims a tool started when CAS lost")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
