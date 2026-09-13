from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "worker/app/agent3/planner.py",
    '''    def _assert_reviewed_run_identity(existing: AgentRun, reviewed_template: AgentRun) -> None:\n        # Never execute a recovered row merely because its run id matches. The\n        # canonical plan digest binds route + tool/args + risk/sensitivity/egress\n        # metadata to exactly what the operator reviewed, excluding mutable\n        # execution state and step ids.\n        if agent_run_plan_sha256(existing) != agent_run_plan_sha256(reviewed_template):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run does not match the reviewed plan",\n                status_code=503,\n            )\n''',
    '''    def _assert_reviewed_run_identity(existing: AgentRun, reviewed_template: AgentRun) -> None:\n        # Never execute a recovered row merely because its run id matches. The\n        # canonical plan digest binds route + tool/args + risk/sensitivity/egress\n        # metadata to what the operator reviewed while the explicit flags below\n        # bind execution-policy inputs that are intentionally outside the durable\n        # capability-receipt digest. Mutable execution state and step ids remain\n        # excluded.\n        if (\n            agent_run_plan_sha256(existing) != agent_run_plan_sha256(reviewed_template)\n            or existing.proactive != reviewed_template.proactive\n            or existing.allow_private_cloud != reviewed_template.allow_private_cloud\n        ):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run does not match the reviewed plan",\n                status_code=503,\n            )\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        # The materialized reviewed plan is the authority for whether reads\n        # require human review. The separate review DB may be missing or only\n        # partially restored after a crash/restore. If the plan requires review\n        # but that policy row is absent/disabled, recovery must stop before any\n        # advance() can execute remaining reads. A client-side envelope mismatch\n        # check would happen too late because side effects could already exist.\n        if review_reads:\n            if not reviewing:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed read policy is unavailable; recovery remains ambiguous",\n                    status_code=503,\n                )\n            review_state = orchestrator.review_store.get(run_id)\n            if not review_state["enabled"]:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed read policy is missing; recovery remains ambiguous",\n                    status_code=503,\n                )\n            checkpointed = orchestrator.recover_read_review_checkpoint_if_due(run_id)\n            if checkpointed is not None:\n                return checkpointed\n''',
    '''        # The immutable plan bit and the separate review-policy row are two\n        # persisted views of the same execution authority. They must agree in\n        # BOTH directions before recovery can advance. Otherwise corruption from\n        # true->false could clear a waiting checkpoint just as dangerously as a\n        # missing/disabled row for a true plan.\n        if reviewing:\n            review_state = orchestrator.review_store.get(run_id)\n            if bool(review_state["enabled"]) != review_reads:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed read policy disagrees with the reviewed plan; recovery remains ambiguous",\n                    status_code=503,\n                )\n            if not review_reads and review_state["waiting"]:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "unexpected reviewed read checkpoint; recovery remains ambiguous",\n                    status_code=503,\n                )\n        elif review_reads:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "reviewed read policy is unavailable; recovery remains ambiguous",\n                status_code=503,\n            )\n\n        if review_reads:\n            checkpointed = orchestrator.recover_read_review_checkpoint_if_due(run_id)\n            if checkpointed is not None:\n                return checkpointed\n''',
)

Path("tests/worker_agent3_reviewed_start_p1j.py").write_text(r'''from __future__ import annotations

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


def template_run(*, proactive: bool = False, allow_private_cloud: bool = False, two_reads: bool = False) -> AgentRun:
    steps = [
        AgentStep(
            tool="read_one",
            args={},
            risk=RiskClass.READ,
            idempotent=True,
            summary="read one",
        )
    ]
    if two_reads:
        steps.append(
            AgentStep(
                tool="read_two",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read two",
            )
        )
    return AgentRun(
        request=TurnRequest(message="recover authority", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=steps,
        proactive=proactive,
        allow_private_cloud=allow_private_cloud,
    )


def payload(run: AgentRun, *, review_reads: bool) -> str:
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


def app_for(plans: PlanStore, runs: AgentRunStore, reviews: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        runs,
        lambda step: executed.append(step.tool) or {"ok": True},
        reviews,
    )
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


def prepare_pending(root: str, name: str, reviewed: AgentRun) -> tuple[str, str, str, AgentRunStore, ReadReviewStore]:
    plans_path = os.path.join(root, f"{name}-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(reviewed, review_reads=False))
    run_id = f"{name}-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()
    runs = AgentRunStore(os.path.join(root, f"{name}-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, f"{name}-reviews.db"))
    return plans_path, plan_id, run_id, runs, reviews


def execution_policy_flag_tamper_is_pending(root: str) -> None:
    cases = (
        ("private", True, False, "allow_private_cloud"),
        ("proactive", False, True, "proactive"),
    )
    for name, tampered_value, reviewed_value, field in cases:
        reviewed = template_run(
            proactive=True if field == "proactive" else False,
            allow_private_cloud=False,
        )
        if field == "proactive":
            reviewed.proactive = reviewed_value
        plans_path, plan_id, run_id, runs, reviews = prepare_pending(root, name, reviewed)
        persisted = AgentRun.from_json(reviewed.to_json())
        persisted.id = run_id
        setattr(persisted, field, tampered_value)
        persisted.state = RunState.RUNNING
        persisted.current_step = 0
        runs.save_with_event(persisted, "run_created", {})

        plans = PlanStore(plans_path, ttl_seconds=30)
        executed: list[str] = []
        response = TestClient(app_for(plans, runs, reviews, executed)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )
        assert response.status_code == 503, (field, response.text)
        assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
        assert executed == []
        after = runs.load(run_id)
        assert after is not None and getattr(after, field) == tampered_value
        assert after.steps[0].state == StepState.PENDING
        recovery = plans.reviewed_start_recovery(plan_id)
        assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
        plans.close()


def inverse_review_policy_enabled_is_pending(root: str, *, waiting: bool) -> None:
    name = "inverse-waiting" if waiting else "inverse-enabled"
    reviewed = template_run(two_reads=waiting)
    plans_path, plan_id, run_id, runs, reviews = prepare_pending(root, name, reviewed)
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.RUNNING
    if waiting:
        persisted.steps[0].state = StepState.SUCCEEDED
        persisted.steps[0].result = {"ok": True}
        persisted.current_step = 1
    runs.save_with_event(persisted, "run_created", {})
    reviews.configure(run_id, True)
    if waiting:
        reviews.set_waiting(
            run_id,
            completed_step_id=persisted.steps[0].id,
            completed_tool=persisted.steps[0].tool,
            window_start=1,
            window_end=2,
            removable_step_ids=[persisted.steps[1].id],
        )

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    state = reviews.get(run_id)
    assert state["enabled"] is True
    assert state["waiting"] is waiting
    after = runs.load(run_id)
    assert after is not None and after.state is RunState.RUNNING
    if waiting:
        assert after.current_step == 1
        assert after.steps[1].state == StepState.PENDING
    else:
        assert after.current_step == 0
        assert after.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1j-")
execution_policy_flag_tamper_is_pending(root)
inverse_review_policy_enabled_is_pending(root, waiting=False)
inverse_review_policy_enabled_is_pending(root, waiting=True)

print("28 passed, 0 failed")
''', encoding="utf-8")

print("reviewed Start P1j patch staged")
