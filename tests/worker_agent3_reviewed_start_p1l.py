from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def make_run(run_id: str) -> AgentRun:
    return AgentRun(
        id=run_id,
        request=TurnRequest(message="cancel checkpoint race", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(tool="read_one", args={}, risk=RiskClass.READ, idempotent=True, summary="read one"),
            AgentStep(tool="read_two", args={}, risk=RiskClass.READ, idempotent=True, summary="read two"),
        ],
    )


def template_run(*, steps: list[AgentStep] | None = None, proactive: bool = False) -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="cancel reviewed start", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps
        or [
            AgentStep(
                tool="read_one",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
        proactive=proactive,
    )


def materialization(run: AgentRun, *, review_reads: bool = False) -> str:
    return json.dumps(
        {
            "run": run.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": review_reads,
        },
        sort_keys=True,
    )


def delayed_checkpoint(reviews: ReadReviewStore):
    entered = threading.Event()
    release = threading.Event()
    original = reviews.set_waiting

    def wrapped(*args, **kwargs):
        entered.set()
        assert release.wait(5), "checkpoint release timed out"
        return original(*args, **kwargs)

    reviews.set_waiting = wrapped  # type: ignore[method-assign]
    return entered, release


def pause_event_commit(runs: AgentRunStore, target_kind: str):
    entered = threading.Event()
    release = threading.Event()
    original = runs.save_with_event_if_unchanged

    def wrapped(run: AgentRun, **kwargs):
        if kwargs.get("kind") == target_kind:
            entered.set()
            assert release.wait(5), f"{target_kind} release timed out"
        return original(run, **kwargs)

    runs.save_with_event_if_unchanged = wrapped  # type: ignore[method-assign]
    return entered, release


def assert_cancelled_without_checkpoint(
    runs: AgentRunStore,
    reviews: ReadReviewStore,
    run_id: str,
) -> None:
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED
    review = reviews.get(run_id)
    assert review["waiting"] is False, review
    kinds = [item["kind"] for item in runs.events(run_id)]
    assert "run_cancelled" in kinds, kinds
    assert "replan_review_required" not in kinds, kinds


def recovery_window_a_cancel_wins(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "recover-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "recover-reviews.db"))
    run = make_run("recover-cancel-run")
    run.steps[0].state = StepState.SUCCEEDED
    run.steps[0].result = {"ok": True}
    reviews.configure(run.id, True)
    runs.save_with_event(run, "run_created", {"review_reads": True})

    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)
    entered, release = delayed_checkpoint(reviews)
    result: dict[str, AgentRun | None] = {}

    def recover() -> None:
        result["run"] = orchestrator.recover_read_review_checkpoint_if_due(run.id)

    thread = threading.Thread(target=recover, daemon=True)
    thread.start()
    assert entered.wait(5), "recovery never reached checkpoint publication"

    progressed = runs.load(run.id)
    assert progressed is not None and progressed.state is RunState.RUNNING
    assert progressed.current_step == 1
    assert progressed.steps[0].state is StepState.SUCCEEDED

    cancelled = orchestrator.cancel(run.id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive()

    returned = result["run"]
    assert returned is not None and returned.state is RunState.CANCELLED
    assert_cancelled_without_checkpoint(runs, reviews, run.id)


def ordinary_read_checkpoint_cancel_wins(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "ordinary-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "ordinary-reviews.db"))
    run = make_run("ordinary-cancel-run")
    reviews.configure(run.id, True)
    runs.save_with_event(run, "run_created", {"review_reads": True})

    executed: list[str] = []

    def executor(step: AgentStep):
        executed.append(step.tool)
        return {"ok": True}

    orchestrator = ReviewingAgent3Orchestrator(runs, executor, reviews)
    entered, release = delayed_checkpoint(reviews)
    result: dict[str, AgentRun] = {}

    def advance() -> None:
        result["run"] = orchestrator.advance(run.id)

    thread = threading.Thread(target=advance, daemon=True)
    thread.start()
    assert entered.wait(5), "ordinary read never reached checkpoint publication"

    progressed = runs.load(run.id)
    assert progressed is not None and progressed.state is RunState.RUNNING
    assert progressed.current_step == 1
    assert progressed.steps[0].state is StepState.SUCCEEDED

    cancelled = orchestrator.cancel(run.id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive()

    returned = result["run"]
    assert returned.state is RunState.CANCELLED
    assert executed == ["read_one"], executed
    assert_cancelled_without_checkpoint(runs, reviews, run.id)


def cancel_after_checkpoint_publication_cleans_waiting(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "published-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "published-reviews.db"))
    run = make_run("published-cancel-run")
    reviews.configure(run.id, True)
    runs.save_with_event(run, "run_created", {"review_reads": True})

    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"ok": True}, reviews)
    checkpointed = orchestrator.advance(run.id)
    assert checkpointed.state is RunState.RUNNING
    assert reviews.get(run.id)["waiting"] is True
    kinds_before = [item["kind"] for item in runs.events(run.id)]
    assert kinds_before.count("replan_review_required") == 1

    cancelled = orchestrator.cancel(run.id)
    assert cancelled.state is RunState.CANCELLED
    assert reviews.get(run.id)["waiting"] is False
    final = runs.load(run.id)
    assert final is not None and final.state is RunState.CANCELLED
    kinds_after = [item["kind"] for item in runs.events(run.id)]
    assert kinds_after.count("replan_review_required") == 1
    assert kinds_after.count("run_cancelled") == 1


def assert_cancel_wins_transition(
    root: str,
    *,
    name: str,
    run: AgentRun,
    target_kind: str,
) -> None:
    runs = AgentRunStore(os.path.join(root, f"{name}-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, f"{name}-reviews.db"))
    run.id = f"{name}-run"
    reviews.configure(run.id, False)
    runs.save_with_event(run, "run_created", {"review_reads": False})

    def unexpected_executor(_step: AgentStep):
        raise AssertionError("executor must not run in transition race")

    orchestrator = ReviewingAgent3Orchestrator(runs, unexpected_executor, reviews)
    entered, release = pause_event_commit(runs, target_kind)
    result: dict[str, AgentRun] = {}
    failure: dict[str, BaseException] = {}

    def advance() -> None:
        try:
            result["run"] = orchestrator.advance(run.id)
        except BaseException as exc:
            failure["error"] = exc

    thread = threading.Thread(target=advance, daemon=True)
    thread.start()
    assert entered.wait(5), f"{name} never reached {target_kind} commit"

    cancelled = orchestrator.cancel(run.id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive(), f"{name} advance did not finish"
    assert "error" not in failure, failure.get("error")

    returned = result["run"]
    assert returned.state is RunState.CANCELLED
    final = runs.load(run.id)
    assert final is not None and final.state is RunState.CANCELLED
    kinds = [item["kind"] for item in runs.events(run.id)]
    assert kinds.count("run_cancelled") == 1, kinds
    assert target_kind not in kinds, kinds


def transition_cas_preserves_cancel(root: str) -> None:
    interrupted = template_run()
    interrupted.steps[0].state = StepState.EXECUTING
    assert_cancel_wins_transition(
        root,
        name="interrupted",
        run=interrupted,
        target_kind="interrupted_execution",
    )

    blocked = template_run(
        proactive=True,
        steps=[
            AgentStep(
                tool="write_one",
                args={},
                risk=RiskClass.WRITE,
                idempotent=False,
                summary="write one",
            )
        ],
    )
    assert_cancel_wins_transition(
        root,
        name="policy-block",
        run=blocked,
        target_kind="policy_decision",
    )

    confirmation = template_run(
        steps=[
            AgentStep(
                tool="write_two",
                args={},
                risk=RiskClass.WRITE,
                idempotent=False,
                summary="write two",
            )
        ]
    )
    assert_cancel_wins_transition(
        root,
        name="confirmation",
        run=confirmation,
        target_kind="confirmation_required",
    )


def build_app(
    orchestrator: ReviewingAgent3Orchestrator,
    plans: PlanStore,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )
    return app


def concurrent_initial_cancel_is_refused(root: str) -> None:
    plans = PlanStore(os.path.join(root, "initial-plans.db"), ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = plans.save(materialization(reviewed))
    runs = AgentRunStore(os.path.join(root, "initial-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "initial-reviews.db"))
    entered = threading.Event()
    release = threading.Event()

    def executor(_step: AgentStep):
        entered.set()
        assert release.wait(5), "initial executor release timed out"
        return {"ok": True}

    orchestrator = ReviewingAgent3Orchestrator(runs, executor, reviews)
    app = build_app(orchestrator, plans)
    result: dict[str, object] = {}

    def start() -> None:
        result["response"] = TestClient(app).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    thread = threading.Thread(target=start, daemon=True)
    thread.start()
    assert entered.wait(5), "initial Start never entered executor"
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1]
    run_id = recovery[1]

    cancelled = orchestrator.cancel(run_id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive(), "initial Start did not finish"

    response = result["response"]
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    final_recovery = plans.reviewed_start_recovery(plan_id)
    assert final_recovery == ("refused", None, None), final_recovery
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED
    assert reviews.get(run_id)["waiting"] is False
    plans.close()


def concurrent_recovery_cancel_is_refused(root: str) -> None:
    plans_path = os.path.join(root, "recovery-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = old.save(materialization(reviewed))
    run_id = "recovered-cancel-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "recovery-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "recovery-reviews.db"))
    reviews.configure(run_id, False)
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    runs.save_with_event(persisted, "run_created", {"review_reads": False})

    entered = threading.Event()
    release = threading.Event()

    def executor(_step: AgentStep):
        entered.set()
        assert release.wait(5), "recovery executor release timed out"
        return {"ok": True}

    orchestrator = ReviewingAgent3Orchestrator(runs, executor, reviews)
    plans = PlanStore(plans_path, ttl_seconds=30)
    app = build_app(orchestrator, plans)
    result: dict[str, object] = {}

    def recover() -> None:
        result["response"] = TestClient(app).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    thread = threading.Thread(target=recover, daemon=True)
    thread.start()
    assert entered.wait(5), "recovered Start never entered executor"
    cancelled = orchestrator.cancel(run_id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive(), "recovered Start did not finish"

    response = result["response"]
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    final_recovery = plans.reviewed_start_recovery(plan_id)
    assert final_recovery == ("refused", None, None), final_recovery
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED
    assert reviews.get(run_id)["waiting"] is False
    plans.close()


def already_cancelled_recovery_clears_stale_checkpoint(root: str) -> None:
    plans_path = os.path.join(root, "checkpoint-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    reviewed = template_run(
        steps=[
            AgentStep(tool="read_one", args={}, risk=RiskClass.READ, idempotent=True),
            AgentStep(tool="read_two", args={}, risk=RiskClass.READ, idempotent=True),
        ]
    )
    plan_id, _ = old.save(materialization(reviewed, review_reads=True))
    run_id = "cancelled-checkpoint-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "checkpoint-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "checkpoint-reviews.db"))
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.steps[0].state = StepState.SUCCEEDED
    persisted.steps[0].result = {"ok": True}
    persisted.current_step = 1
    persisted.state = RunState.CANCELLED
    persisted.error = "Cancelled by user"
    reviews.configure(run_id, True)
    reviews.set_waiting(
        run_id,
        completed_step_id=persisted.steps[0].id,
        completed_tool=persisted.steps[0].tool,
        window_start=1,
        window_end=2,
        removable_step_ids=[persisted.steps[1].id],
    )
    runs.save_with_event(persisted, "run_cancelled", {})

    def unexpected_executor(_step: AgentStep):
        raise AssertionError("cancelled recovery executed")

    orchestrator = ReviewingAgent3Orchestrator(runs, unexpected_executor, reviews)
    plans = PlanStore(plans_path, ttl_seconds=30)
    response = TestClient(build_app(orchestrator, plans)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    assert plans.reviewed_start_recovery(plan_id) == ("refused", None, None)
    assert reviews.get(run_id)["waiting"] is False
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1l-")
recovery_window_a_cancel_wins(root)
ordinary_read_checkpoint_cancel_wins(root)
cancel_after_checkpoint_publication_cleans_waiting(root)
transition_cas_preserves_cancel(root)
concurrent_initial_cancel_is_refused(root)
concurrent_recovery_cancel_is_refused(root)
already_cancelled_recovery_clears_stale_checkpoint(root)
print("P1l+: cancellation/reviewed-Start authority races passed")
