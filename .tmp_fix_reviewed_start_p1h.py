from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "worker/app/agent3/plan_store.py",
    '''    def mark_reviewed_start_accepted(self, plan_id: str, run_id: str) -> None:\n''',
    '''    def release_reviewed_start_recovery(self, plan_id: str, run_id: str) -> bool:\n        """Release this worker's pending recovery claim after materialized recovery exits."""\n        now = time.time()\n        with self._lock:\n            with self._connection() as connection:\n                try:\n                    connection.execute("BEGIN IMMEDIATE")\n                    row = connection.execute(\n                        "SELECT state,run_id,owner FROM agent_reviewed_starts WHERE plan_id=?",\n                        (plan_id,),\n                    ).fetchone()\n                    if row is None:\n                        raise PlanStoreError("reviewed Start recovery not found")\n                    state, existing_run_id, owner_raw = row\n                    if state != "pending" or existing_run_id != run_id:\n                        connection.commit()\n                        return False\n                    owner = self._owner_value(owner_raw)\n                    if owner != self._start_owner:\n                        connection.commit()\n                        return False\n                    changed = connection.execute(\n                        "UPDATE agent_reviewed_starts SET owner=NULL,updated_at=? "\n                        "WHERE plan_id=? AND state='pending' AND run_id=? AND owner=?",\n                        (now, plan_id, run_id, self._start_owner),\n                    ).rowcount\n                    connection.commit()\n                    return changed == 1\n                except Exception:\n                    connection.rollback()\n                    raise\n\n    def mark_reviewed_start_accepted(self, plan_id: str, run_id: str) -> None:\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''    @router.post("/plans/{plan_id}/start")\n''',
    '''    def _recover_materialized_reviewed_start(\n        plan_id: str,\n        run_id: str,\n        stored: dict[str, Any],\n        *,\n        review_reads: bool,\n    ) -> dict[str, Any]:\n        # Once the exact reserved run exists, a failed reconciliation/finalization\n        # must not leave this worker generation holding the durable recovery claim\n        # forever. Release only after this execution path is exiting; a later\n        # request must claim the same run again before it can reconcile anything.\n        try:\n            reconciled = _reconcile_reviewed_start_run(\n                run_id,\n                review_reads=review_reads,\n            )\n            plan_store.mark_reviewed_start_accepted(plan_id, run_id)\n            return _reviewed_start_response(plan_id, stored, reconciled)\n        except Exception:\n            plan_store.release_reviewed_start_recovery(plan_id, run_id)\n            raise\n\n    @router.post("/plans/{plan_id}/start")\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''                except (TypeError, json.JSONDecodeError, ValueError) as exc:\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "persisted reviewed Start policy is unreadable; recovery remains ambiguous",\n                        status_code=503,\n                    ) from exc\n                reconciled = _reconcile_reviewed_start_run(\n                    reserved_run_id,\n                    review_reads=recovered_review_reads,\n                )\n                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n                stored = recovery_envelope\n                return _reviewed_start_response(plan_id, stored, reconciled)\n''',
    '''                except (TypeError, json.JSONDecodeError, ValueError) as exc:\n                    plan_store.release_reviewed_start_recovery(plan_id, reserved_run_id)\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "persisted reviewed Start policy is unreadable; recovery remains ambiguous",\n                        status_code=503,\n                    ) from exc\n                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    recovery_envelope,\n                    review_reads=recovered_review_reads,\n                )\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        except HTTPException:\n            existing = orchestrator.store.load(reserved_run_id)\n            if existing is not None:\n                reconciled = _reconcile_reviewed_start_run(\n                    reserved_run_id,\n                    review_reads=review_reads,\n                )\n                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n                return _reviewed_start_response(plan_id, envelope, reconciled)\n            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)\n            raise\n        except Exception:\n            existing = orchestrator.store.load(reserved_run_id)\n            if existing is not None:\n                reconciled = _reconcile_reviewed_start_run(\n                    reserved_run_id,\n                    review_reads=review_reads,\n                )\n                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n                return _reviewed_start_response(plan_id, envelope, reconciled)\n            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)\n            raise\n''',
    '''        except HTTPException:\n            existing = orchestrator.store.load(reserved_run_id)\n            if existing is not None:\n                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                )\n            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)\n            raise\n        except Exception:\n            existing = orchestrator.store.load(reserved_run_id)\n            if existing is not None:\n                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                )\n            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)\n            raise\n''',
)

Path("tests/worker_agent3_reviewed_start_p1h.py").write_text(r'''from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
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


def materialization() -> str:
    template = AgentRun(
        request=TurnRequest(message="recover same worker", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            ),
            AgentStep(
                tool="read_two",
                args={},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read two",
            ),
        ],
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


def run_case(root: str, *, exception_kind: str) -> None:
    plans = PlanStore(os.path.join(root, f"{exception_kind}-plans.db"), ttl_seconds=30)
    plan_id, _ = plans.save(materialization())
    run_store = AgentRunStore(os.path.join(root, f"{exception_kind}-runs.db"))
    review_store = ReadReviewStore(os.path.join(root, f"{exception_kind}-reviews.db"))
    executed: list[str] = []
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
    )

    original_mark = plans.mark_reviewed_start_accepted
    mark_calls = 0

    def fail_two_marks(bound_plan_id: str, run_id: str) -> None:
        nonlocal mark_calls
        mark_calls += 1
        if mark_calls <= 2:
            if exception_kind == "http":
                raise HTTPException(status_code=503, detail="transient acceptance failure")
            raise RuntimeError("transient acceptance failure")
        original_mark(bound_plan_id, run_id)

    plans.mark_reviewed_start_accepted = fail_two_marks  # type: ignore[method-assign]

    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )
    client = TestClient(app, raise_server_exceptions=False)

    first = client.post(f"/experimental/agent3/plans/{plan_id}/start")
    assert first.status_code == (503 if exception_kind == "http" else 500), first.text
    assert mark_calls == 2
    assert executed == ["read_one"]

    pending = plans.reviewed_start_recovery(plan_id)
    assert pending is not None
    assert pending[0] == "pending"
    run_id = pending[1]
    assert run_id is not None
    assert pending[2] is None

    persisted = run_store.load(run_id)
    assert persisted is not None
    assert persisted.state == RunState.RUNNING
    assert persisted.current_step == 1
    assert persisted.steps[0].state == StepState.SUCCEEDED
    assert persisted.steps[1].state == StepState.PENDING
    assert review_store.get(run_id)["enabled"] is True
    assert review_store.get(run_id)["waiting"] is True

    second = client.post(f"/experimental/agent3/plans/{plan_id}/start")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["state"] == "running"
    assert body["read_review"]["waiting"] is True
    assert executed == ["read_one"]
    assert mark_calls == 3

    accepted = plans.reviewed_start_recovery(plan_id)
    assert accepted is not None
    assert accepted[0] == "accepted"
    assert accepted[1] == run_id
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1h-")
run_case(root, exception_kind="runtime")
run_case(root, exception_kind="http")

print("28 passed, 0 failed")
''', encoding="utf-8")

print("reviewed Start P1h patch staged")
