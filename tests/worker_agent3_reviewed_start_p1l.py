from __future__ import annotations

import os
import tempfile
import threading

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    TurnRequest,
)
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


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


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1l-")
recovery_window_a_cancel_wins(root)
ordinary_read_checkpoint_cancel_wins(root)
cancel_after_checkpoint_publication_cleans_waiting(root)
print("P1l: cancellation/checkpoint publication races passed")
