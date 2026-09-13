from pathlib import Path

path = Path("worker/app/agent3/review_orchestrator.py")
text = path.read_text(encoding="utf-8")

if "def clear_waiting_if_matches(" in text or "def _publish_read_review_checkpoint(" in text:
    raise SystemExit("P1l markers already present")

old = '''    def resume(\n        self,\n        run_id: str,\n        *,\n        expected_completed_step_id: str | None = None,\n    ) -> dict | None:\n'''
new = '''    def clear_waiting_if_matches(\n        self,\n        run_id: str,\n        *,\n        expected_completed_step_id: str | None = None,\n    ) -> bool:\n        \"\"\"Clear only checkpoint authority that still belongs to this run/step.\"\"\"\n        with self._lock:\n            self._conn.execute("BEGIN IMMEDIATE")\n            try:\n                if expected_completed_step_id is None:\n                    changed = self._conn.execute(\n                        "UPDATE agent_read_reviews SET waiting=0,window_start=NULL,window_end=NULL,"\n                        "removable_step_ids='[]',completed_step_id=NULL,completed_tool=NULL,updated_at=? "\n                        "WHERE run_id=? AND waiting=1",\n                        (time.time(), run_id),\n                    ).rowcount\n                else:\n                    changed = self._conn.execute(\n                        "UPDATE agent_read_reviews SET waiting=0,window_start=NULL,window_end=NULL,"\n                        "removable_step_ids='[]',completed_step_id=NULL,completed_tool=NULL,updated_at=? "\n                        "WHERE run_id=? AND waiting=1 AND completed_step_id=?",\n                        (time.time(), run_id, expected_completed_step_id),\n                    ).rowcount\n                self._conn.commit()\n                return changed == 1\n            except Exception:\n                self._conn.rollback()\n                raise\n\n    def resume(\n        self,\n        run_id: str,\n        *,\n        expected_completed_step_id: str | None = None,\n    ) -> dict | None:\n'''
if old not in text:
    raise SystemExit("missing ReadReviewStore insertion anchor")
text = text.replace(old, new, 1)

old = '''    def recover_read_review_checkpoint_if_due(self, run_id: str) -> AgentRun | None:\n'''
new = '''    def _publish_read_review_checkpoint(\n        self,\n        run: AgentRun,\n        *,\n        completed: AgentStep,\n        start: int,\n        end: int,\n        removable_ids: list[str],\n        recovered: bool,\n    ) -> AgentRun | None:\n        \"\"\"Publish checkpoint only while the exact RUNNING snapshot remains authority.\n\n        The review row lives in a second SQLite database, so publication cannot\n        be one cross-store transaction. We make the review row durable first\n        (fail-closed on crash), then use the run payload as a CAS publication\n        fence. If Cancel wins that fence, only the checkpoint we just installed\n        is removed and the durable CANCELLED run is returned.\n        \"\"\"\n        expected_payload = run.to_json()\n        self.review_store.set_waiting(\n            run.id,\n            completed_step_id=completed.id,\n            completed_tool=completed.tool,\n            window_start=start,\n            window_end=end,\n            removable_step_ids=removable_ids,\n        )\n        payload = {\n            "completed_step_id": completed.id,\n            "completed_tool": completed.tool,\n            "window_start": start,\n            "window_end": end,\n            "removable_step_ids": removable_ids,\n        }\n        if recovered:\n            payload["recovered"] = True\n        if self.store.save_with_event_if_unchanged(\n            run,\n            expected_state=RunState.RUNNING,\n            expected_payload=expected_payload,\n            kind="replan_review_required",\n            payload=payload,\n        ):\n            return None\n\n        self.review_store.clear_waiting_if_matches(\n            run.id, expected_completed_step_id=completed.id\n        )\n        fresh = self._require(run.id)\n        if fresh.state == RunState.CANCELLED:\n            return fresh\n        raise RunConflict("run changed while read review checkpoint was being published")\n\n    def recover_read_review_checkpoint_if_due(self, run_id: str) -> AgentRun | None:\n'''
if old not in text:
    raise SystemExit("missing checkpoint helper insertion anchor")
text = text.replace(old, new, 1)

old = '''        self.review_store.set_waiting(\n            run.id,\n            completed_step_id=completed.id,\n            completed_tool=completed.tool,\n            window_start=start,\n            window_end=end,\n            removable_step_ids=removable_ids,\n        )\n        self.store.event(\n            run.id,\n            "replan_review_required",\n            {\n                "completed_step_id": completed.id,\n                "completed_tool": completed.tool,\n                "window_start": start,\n                "window_end": end,\n                "removable_step_ids": removable_ids,\n                "recovered": True,\n            },\n        )\n        return run\n'''
new = '''        conflict = self._publish_read_review_checkpoint(\n            run,\n            completed=completed,\n            start=start,\n            end=end,\n            removable_ids=removable_ids,\n            recovered=True,\n        )\n        return conflict if conflict is not None else run\n'''
if old not in text:
    raise SystemExit("missing recovery checkpoint publication block")
text = text.replace(old, new, 1)

old = '''                    self.review_store.set_waiting(\n                        run.id,\n                        completed_step_id=step.id,\n                        completed_tool=step.tool,\n                        window_start=start,\n                        window_end=end,\n                        removable_step_ids=removable_ids,\n                    )\n                    self.store.event(\n                        run.id,\n                        "replan_review_required",\n                        {\n                            "completed_step_id": step.id,\n                            "completed_tool": step.tool,\n                            "window_start": start,\n                            "window_end": end,\n                            "removable_step_ids": removable_ids,\n                        },\n                    )\n                    return run\n'''
new = '''                    conflict = self._publish_read_review_checkpoint(\n                        run,\n                        completed=step,\n                        start=start,\n                        end=end,\n                        removable_ids=removable_ids,\n                        recovered=False,\n                    )\n                    return conflict if conflict is not None else run\n'''
if old not in text:
    raise SystemExit("missing ordinary checkpoint publication block")
text = text.replace(old, new, 1)

old = '''    def advance(\n        self,\n        run_id: str,\n        *,\n        expected_review_step_id: str | None = None,\n    ) -> AgentRun:\n'''
new = '''    def cancel(self, run_id: str) -> AgentRun:\n        run = super().cancel(run_id)\n        if run.state == RunState.CANCELLED:\n            # A terminal stop owns authority over any older human-read checkpoint.\n            # This also closes the opposite ordering where checkpoint publication\n            # linearizes immediately before a concurrent Cancel.\n            self.review_store.clear_waiting_if_matches(run.id)\n        return run\n\n    def advance(\n        self,\n        run_id: str,\n        *,\n        expected_review_step_id: str | None = None,\n    ) -> AgentRun:\n'''
if old not in text:
    raise SystemExit("missing cancel insertion anchor")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

test = Path("tests/worker_agent3_reviewed_start_p1l.py")
if test.exists():
    raise SystemExit("P1l regression already exists")
test.write_text(r'''from __future__ import annotations

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
''', encoding="utf-8")

print("applied P1l cancellation/checkpoint publication fix and regression")
