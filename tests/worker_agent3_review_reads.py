from __future__ import annotations

import json
import os
import tempfile

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    EgressClass,
    RiskClass,
    RunState,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_step(tool, risk=RiskClass.READ, args=None):
    return AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="conv-1",
        summary=f"summary:{tool}",
    )


class Executor:
    def __init__(self):
        self.calls = []

    def __call__(self, step):
        self.calls.append(step.tool)
        return {"tool": step.tool, "call": len(self.calls)}


root = tempfile.mkdtemp(prefix="agent3-review-reads-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
review_store = ReadReviewStore(os.path.join(root, "reviews.db"))
executor = Executor()
orch = ReviewingAgent3Orchestrator(
    run_store,
    executor,
    review_store,
    confirmation_ttl_seconds=60,
)
caps = CapabilitySnapshot(
    rig_reachable=True,
    worker_ready=True,
    tools_ready=True,
    cloud_ready=False,
    rag_ready=True,
)
request = TurnRequest(
    "review reads",
    mode="rig",
    tools=True,
    conversation_id="conv-1",
)

# Reviewed run: exactly one successful read per explicit advance while more reads remain.
steps = [
    make_step("read_one"),
    make_step("read_two"),
    make_step("read_three"),
    make_step("write_one", RiskClass.WRITE, {"value": "fixed"}),
]
run = orch.start_with_steps(request, caps, steps, review_reads=True)
check(run.state == RunState.RUNNING, "reviewed run remains running at checkpoint")
check(run.current_step == 1, "first read advances current_step once")
check(executor.calls == ["read_one"], "start executes only the first read")
review = review_store.get(run.id)
check(review["enabled"] is True and review["waiting"] is True, "review checkpoint is persisted")
check(review["window_start"] == 1 and review["window_end"] == 3, "checkpoint binds pending read window")
check(review["removable_step_ids"] == [steps[1].id, steps[2].id], "checkpoint binds exact removable ids")

reloaded = run_store.load(run.id)
check(reloaded.current_step == 1 and review_store.get(run.id)["waiting"], "checkpoint survives reload")

events = run_store.events(run.id)
required = [event for event in events if event["kind"] == "replan_review_required"]
check(len(required) == 1, "first checkpoint is auditable")
check(required[0]["payload"]["completed_tool"] == "read_one", "event identifies completed read")

run = orch.advance(run.id)
check(run.current_step == 2 and executor.calls == ["read_one", "read_two"], "explicit resume executes exactly one next read")
check(review_store.get(run.id)["waiting"] is True, "second read creates a new checkpoint")
events = [event["kind"] for event in run_store.events(run.id)]
check(events.count("replan_review_resumed") == 1, "resume event is persisted")
check(events.count("replan_review_required") == 2, "second checkpoint is persisted")

run = orch.advance(run.id)
check(executor.calls == ["read_one", "read_two", "read_three"], "third resume executes final read")
check(run.state == RunState.WAITING_CONFIRMATION, "run reaches write confirmation after final read")
check(run.current_step == 3, "write remains the current immutable step")
check(review_store.get(run.id)["waiting"] is False, "no review checkpoint is created before a write")
write = run.steps[3]
check(write.state == StepState.WAITING_CONFIRMATION, "write step is untouched and awaits confirmation")

run = orch.confirm(run.id, write.id, "approve", write.confirmation_digest)
check(run.state == RunState.COMPLETED, "approved write completes reviewed run")
check(executor.calls[-1] == "write_one", "write executes only after confirmation")

# Applying/removing a pending read window does not resume the reviewed run by itself.
manual_steps = [make_step("read_a"), make_step("read_b"), make_step("read_c")]
manual = orch.start_with_steps(request, caps, manual_steps, review_reads=True)
check(review_store.get(manual.id)["waiting"] is True, "second reviewed run pauses")
manual.steps[1:3] = [make_step("replacement_read")]
run_store.save(manual)
check(review_store.get(manual.id)["waiting"] is True, "plan mutation alone does not resume checkpoint")
manual = orch.advance(manual.id)
check(executor.calls[-1] == "replacement_read", "explicit advance runs replacement read")
check(manual.state == RunState.COMPLETED, "replacement final read completes run")

# Default mode preserves old behavior: all reads execute before write confirmation.
plain_executor = Executor()
plain = ReviewingAgent3Orchestrator(
    run_store,
    plain_executor,
    review_store,
    confirmation_ttl_seconds=60,
)
plain_steps = [
    make_step("plain_read_one"),
    make_step("plain_read_two"),
    make_step("plain_write", RiskClass.WRITE),
]
plain_run = plain.start_with_steps(request, caps, plain_steps)
check(plain_executor.calls == ["plain_read_one", "plain_read_two"], "default run executes contiguous reads without pause")
check(plain_run.state == RunState.WAITING_CONFIRMATION, "default run retains existing confirmation behavior")
check(review_store.get(plain_run.id)["enabled"] is False, "default run has review mode disabled")

# Read-only reviewed run pauses between reads and then completes normally.
only_executor = Executor()
only = ReviewingAgent3Orchestrator(run_store, only_executor, review_store)
only_run = only.start_with_steps(
    request,
    caps,
    [make_step("only_one"), make_step("only_two")],
    review_reads=True,
)
check(only_run.current_step == 1 and review_store.get(only_run.id)["waiting"], "read-only run pauses before final read")
only_run = only.advance(only_run.id)
check(only_run.state == RunState.COMPLETED, "read-only run completes after explicit resume")
check(review_store.get(only_run.id)["waiting"] is False, "completed read-only run has no waiting checkpoint")

# Existing AgentRun JSON stays unchanged and backward-compatible.
legacy = AgentRun(
    request=request,
    route=plain_run.route,
    steps=[make_step("legacy")],
)
payload = json.loads(legacy.to_json())
check("review_reads" not in payload and "waiting_replan" not in payload, "review policy does not migrate AgentRun schema")
roundtrip = AgentRun.from_json(json.dumps(payload))
check(roundtrip.state == RunState.RUNNING and roundtrip.current_step == 0, "legacy AgentRun roundtrip remains valid")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
