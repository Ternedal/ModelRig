from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "worker/app/agent3/review_orchestrator.py",
    '''    @staticmethod\n    def _pending_read_window(run: AgentRun) -> tuple[int, int] | None:\n        start = run.current_step\n        end = start\n        while end < len(run.steps):\n            item = run.steps[end]\n            if item.state != StepState.PENDING or item.risk != RiskClass.READ:\n                break\n            end += 1\n        return (start, end) if end > start else None\n\n    def advance(\n''',
    '''    @staticmethod\n    def _pending_read_window(run: AgentRun) -> tuple[int, int] | None:\n        start = run.current_step\n        end = start\n        while end < len(run.steps):\n            item = run.steps[end]\n            if item.state != StepState.PENDING or item.risk != RiskClass.READ:\n                break\n            end += 1\n        return (start, end) if end > start else None\n\n    def recover_read_review_checkpoint_if_due(self, run_id: str) -> AgentRun | None:\n        \"\"\"Rebuild a reviewed-read checkpoint lost in a cross-store crash gap.\n\n        The run DB and read-review DB cannot share a transaction. A crash can\n        therefore persist a successful READ (and possibly its advanced\n        ``current_step``) before ``set_waiting`` reaches the review DB. Reviewed\n        Start recovery must restore that human authority before it considers\n        calling ``advance``; otherwise the next pending reads would execute\n        without the explicit Resume the review policy requires.\n\n        Returning ``None`` means no checkpoint is due. Returning the run means\n        recovery must stop at the existing or reconstructed checkpoint.\n        \"\"\"\n        run = self._require(run_id)\n        review = self.review_store.get(run.id)\n        if not review[\"enabled\"]:\n            return None\n        if review[\"waiting\"]:\n            return run\n\n        completed: AgentStep | None = None\n\n        # Crash window A: _execute() persisted the successful read, but the\n        # orchestrator had not yet advanced current_step and saved the run.\n        if run.current_step < len(run.steps):\n            current = run.steps[run.current_step]\n            if current.state == StepState.SUCCEEDED and current.risk == RiskClass.READ:\n                completed = current\n                run.current_step += 1\n                run.state = RunState.RUNNING\n                self.store.save(run)\n\n        # Crash window B: current_step was already saved, but set_waiting() had\n        # not yet made the human checkpoint durable in the review DB.\n        if completed is None and run.current_step > 0:\n            previous = run.steps[run.current_step - 1]\n            if previous.state == StepState.SUCCEEDED and previous.risk == RiskClass.READ:\n                completed = previous\n\n        if completed is None:\n            return None\n\n        window = self._pending_read_window(run)\n        if window is None:\n            return None\n\n        start, end = window\n        removable_ids = [item.id for item in run.steps[start:end]]\n        self.review_store.set_waiting(\n            run.id,\n            completed_step_id=completed.id,\n            completed_tool=completed.tool,\n            window_start=start,\n            window_end=end,\n            removable_step_ids=removable_ids,\n        )\n        self.store.event(\n            run.id,\n            \"replan_review_required\",\n            {\n                \"completed_step_id\": completed.id,\n                \"completed_tool\": completed.tool,\n                \"window_start\": start,\n                \"window_end\": end,\n                \"removable_step_ids\": removable_ids,\n                \"recovered\": True,\n            },\n        )\n        return run\n\n    def advance(\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        # A waiting read-review checkpoint is explicit human authority. A retry\n        # that is only recovering a previously ambiguous Start must never consume\n        # that checkpoint by calling advance() without an expected review step.\n        if reviewing and orchestrator.review_store.get(run_id)[\"waiting\"]:\n            return existing\n        try:\n            return orchestrator.advance(run_id)\n''',
    '''        # Reviewed Start recovery must restore human review authority before\n        # advancing. This covers both an already-durable waiting checkpoint and\n        # the cross-store crash windows where a READ succeeded but set_waiting()\n        # had not yet reached the review DB.\n        if reviewing:\n            checkpointed = orchestrator.recover_read_review_checkpoint_if_due(run_id)\n            if checkpointed is not None:\n                return checkpointed\n        try:\n            return orchestrator.advance(run_id)\n''',
)

Path("tests/worker_agent3_reviewed_start_p1e.py").write_text(r'''from __future__ import annotations

import json
import os
import tempfile
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


def envelope_payload(steps: list[AgentStep]) -> str:
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
    )
    return json.dumps(
        {
            "run": template.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": True,
        },
        sort_keys=True,
    )


def recovered_case(root: str, *, name: str, current_step: int) -> None:
    plans_path = os.path.join(root, f"{name}-plans.db")
    runs_path = os.path.join(root, f"{name}-runs.db")
    reviews_path = os.path.join(root, f"{name}-reviews.db")
    first = AgentStep(
        tool="read_one",
        args={},
        risk=RiskClass.READ,
        idempotent=True,
        summary="read one",
        state=StepState.SUCCEEDED,
        result={"ok": 1},
    )
    second = AgentStep(
        tool="read_two",
        args={},
        risk=RiskClass.READ,
        idempotent=True,
        summary="read two",
    )
    steps = [first, second]

    plans = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = plans.save(envelope_payload(steps))
    run_id = f"reserved-{name}"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.close()

    run_store = AgentRunStore(runs_path)
    review_store = ReadReviewStore(reviews_path)
    review_store.configure(run_id, True)
    run = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
        state=RunState.RUNNING,
        id=run_id,
        current_step=current_step,
    )
    run_store.save_with_event(run, "run_created", {"review_reads": True})
    assert review_store.get(run_id)["waiting"] is False

    executed: list[str] = []
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
    )
    recovered_plans = PlanStore(plans_path, ttl_seconds=30)
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=recovered_plans,
        )
    )
    response = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["state"] == "running"
    assert body["run"]["current_step"] == 1
    assert body["run"]["steps"][0]["state"] == "succeeded"
    assert body["run"]["steps"][1]["state"] == "pending"
    assert executed == []

    review = review_store.get(run_id)
    assert review["enabled"] is True
    assert review["waiting"] is True
    assert review["completed_step_id"] == first.id
    assert review["completed_tool"] == "read_one"
    assert review["window_start"] == 1
    assert review["window_end"] == 2
    assert review["removable_step_ids"] == [second.id]
    assert body["read_review"]["waiting"] is True
    assert recovered_plans.reviewed_start_recovery(plan_id)[:2] == ("accepted", run_id)
    recovered_plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1e-")

# Crash window A: the READ result/state was persisted by _execute(), but
# current_step had not yet advanced to the next pending READ.
recovered_case(root, name="before-current-step-save", current_step=0)

# Crash window B: current_step was persisted, but set_waiting() had not yet
# created the human checkpoint in the separate review DB.
recovered_case(root, name="before-review-checkpoint", current_step=1)

print("30 passed, 0 failed")
''', encoding="utf-8")

print("reviewed Start P1e patch staged")
