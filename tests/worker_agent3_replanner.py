from __future__ import annotations

from copy import deepcopy

from app.agent3.core import (
    AgentRun,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.replanner import ReadSuffixReplanner, ReplanError


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(fn, name):
    try:
        fn()
    except ReplanError:
        check(True, name)
    else:
        check(False, name)


def route(*, cloud=False):
    return RoutePlan(
        RouteKind.RIG_TOOLS_CLOUD if cloud else RouteKind.RIG_TOOLS_LOCAL,
        "test route",
        uses_cloud=cloud,
        uses_rig=True,
        uses_tools=True,
        uses_rag=False,
    )


def step(
    tool,
    risk=RiskClass.READ,
    *,
    state=StepState.PENDING,
    cloud=False,
    conversation_id="conv-1",
    args=None,
):
    return AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.CLOUD if cloud else EgressClass.LOCAL,
        origin="cloud" if cloud else "local",
        conversation_id=conversation_id,
        summary=f"summary:{tool}",
        state=state,
    )


def make_run(*, cloud=False):
    completed = step("rig_status", state=StepState.SUCCEEDED, cloud=cloud)
    completed.result = "online"
    read_a = step("list_models", cloud=cloud)
    read_b = step("current_datetime", cloud=cloud)
    write = step(
        "note_append",
        RiskClass.WRITE,
        cloud=cloud,
        args={"text": "immutable write"},
    )
    return AgentRun(
        request=TurnRequest(
            "test",
            mode="cloud" if cloud else "rig",
            tools=True,
            conversation_id="conv-1",
        ),
        route=route(cloud=cloud),
        steps=[completed, read_a, read_b, write],
        current_step=1,
    )


replanner = ReadSuffixReplanner(max_steps=6, max_replans=3)
run = make_run()
prefix_before = deepcopy(run.steps[0])
tail_before = deepcopy(run.steps[3])
replacement = [step("rig_status", args={"detail": True})]
receipt = replanner.apply(
    run,
    replacement,
    reason="The first read made the second read unnecessary",
    revision=4,
    replan_count=1,
    now=123.0,
)

check([s.tool for s in run.steps] == ["rig_status", "rig_status", "note_append"], "only pending read window is replaced")
check(run.current_step == 1, "current_step remains at the replacement window")
check(run.steps[0].id == prefix_before.id and run.steps[0].result == "online", "completed prefix is byte-semantically preserved")
check(
    run.steps[-1].id == tail_before.id
    and run.steps[-1].args == {"text": "immutable write"}
    and run.steps[-1].risk == RiskClass.WRITE,
    "write tail is preserved",
)
check(receipt.from_revision == 4 and receipt.to_revision == 5 and receipt.replan_number == 2, "receipt advances bounded revision metadata")
check(receipt.timestamp == 123.0 and receipt.added_tools == ("rig_status",), "receipt is deterministic and auditable")
check(receipt.immutable_prefix_ids == (prefix_before.id,), "receipt binds immutable prefix")
check(receipt.immutable_tail_ids == (tail_before.id,), "receipt binds immutable tail")

empty_run = make_run()
empty_tail_id = empty_run.steps[3].id
empty_receipt = replanner.apply(
    empty_run,
    [],
    reason="No additional reads are required",
    revision=0,
    replan_count=0,
)
check([s.tool for s in empty_run.steps] == ["rig_status", "note_append"], "empty replacement may remove redundant reads")
check(empty_run.steps[-1].id == empty_tail_id and empty_receipt.added_step_ids == (), "empty replacement cannot remove side-effect tail")

expect_error(
    lambda: replanner.apply(
        make_run(),
        [step("note_append", RiskClass.WRITE, args={"text": "bad"})],
        reason="bad",
        revision=0,
        replan_count=0,
    ),
    "replacement writes are rejected",
)

waiting = make_run()
waiting.state = RunState.WAITING_CONFIRMATION
expect_error(
    lambda: replanner.apply(waiting, [step("rig_status")], reason="bad", revision=0, replan_count=0),
    "waiting-confirmation run is immutable",
)

write_current = make_run()
write_current.current_step = 3
expect_error(
    lambda: replanner.apply(write_current, [], reason="bad", revision=0, replan_count=0),
    "current write step cannot be replanned",
)

not_fresh = step("rig_status")
not_fresh.result = "already executed"
expect_error(
    lambda: replanner.apply(make_run(), [not_fresh], reason="bad", revision=0, replan_count=0),
    "replacement steps must be fresh",
)

confirmation_state = step("rig_status")
confirmation_state.confirmation_digest = "x" * 64
expect_error(
    lambda: replanner.apply(make_run(), [confirmation_state], reason="bad", revision=0, replan_count=0),
    "replacement cannot carry confirmation state",
)

expect_error(
    lambda: replanner.apply(
        make_run(),
        [step("rig_status", cloud=True)],
        reason="bad",
        revision=0,
        replan_count=0,
    ),
    "replacement cannot change local route semantics",
)

cloud_run = make_run(cloud=True)
cloud_receipt = replanner.apply(
    cloud_run,
    [step("rig_status", cloud=True)],
    reason="cloud read revision",
    revision=0,
    replan_count=0,
)
check(cloud_run.steps[1].egress == EgressClass.CLOUD and cloud_receipt.to_revision == 1, "cloud read replanning preserves cloud route")

wrong_conversation = step("rig_status", conversation_id="other")
expect_error(
    lambda: replanner.apply(make_run(), [wrong_conversation], reason="bad", revision=0, replan_count=0),
    "replacement cannot change conversation binding",
)

collision_run = make_run()
collision = step("rig_status")
collision.id = collision_run.steps[0].id
expect_error(
    lambda: replanner.apply(collision_run, [collision], reason="bad", revision=0, replan_count=0),
    "replacement cannot reuse an immutable step id",
)

expect_error(
    lambda: replanner.apply(make_run(), [step("rig_status")], reason="bad", revision=0, replan_count=3),
    "max_replans is enforced",
)

small_budget = ReadSuffixReplanner(max_steps=3, max_replans=3)
expect_error(
    lambda: small_budget.apply(
        make_run(),
        [step("rig_status"), step("list_models"), step("current_datetime")],
        reason="too many",
        revision=0,
        replan_count=0,
    ),
    "max_steps is enforced after replacement",
)

expect_error(
    lambda: replanner.apply(make_run(), [step("rig_status")], reason="   ", revision=0, replan_count=0),
    "replan reason is mandatory",
)

expect_error(
    lambda: replanner.apply(make_run(), [step("rig_status")], reason="x", revision=-1, replan_count=0),
    "negative revision is rejected",
)

completed_run = make_run()
completed_run.current_step = len(completed_run.steps)
expect_error(
    lambda: replanner.apply(completed_run, [], reason="late", revision=0, replan_count=0),
    "run without a current pending step cannot be replanned",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
