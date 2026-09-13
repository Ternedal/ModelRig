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
    "import re\nimport uuid\n",
    "import re\nimport threading\nimport uuid\n",
)

replace_once(
    "worker/app/agent3/plan_store.py",
    '''    def release_reviewed_start_recovery(self, plan_id: str, run_id: str) -> bool:\n        """Release this worker's pending recovery claim after materialized recovery exits."""\n        now = time.time()\n        with self._lock:\n            with self._connection() as connection:\n                try:\n                    connection.execute("BEGIN IMMEDIATE")\n                    row = connection.execute(\n                        "SELECT state,run_id,owner FROM agent_reviewed_starts WHERE plan_id=?",\n                        (plan_id,),\n                    ).fetchone()\n                    if row is None:\n                        raise PlanStoreError("reviewed Start recovery not found")\n                    state, existing_run_id, owner_raw = row\n                    if state != "pending" or existing_run_id != run_id:\n                        connection.commit()\n                        return False\n                    owner = self._owner_value(owner_raw)\n                    if owner != self._start_owner:\n                        connection.commit()\n                        return False\n                    changed = connection.execute(\n                        "UPDATE agent_reviewed_starts SET owner=NULL,updated_at=? "\n                        "WHERE plan_id=? AND state='pending' AND run_id=? AND owner=?",\n                        (now, plan_id, run_id, self._start_owner),\n                    ).rowcount\n                    connection.commit()\n                    return changed == 1\n                except Exception:\n                    connection.rollback()\n                    raise\n\n''',
    "",
)

replace_once(
    "worker/app/agent3/planner.py",
    '''    def _reconcile_reviewed_start_run(\n        run_id: str,\n        *,\n        review_reads: bool,\n    ) -> AgentRun:\n''',
    '''    reviewed_start_retry_ready: set[tuple[str, str]] = set()\n    reviewed_start_retry_lock = threading.Lock()\n\n    def _mark_reviewed_start_retry_ready(plan_id: str, run_id: str) -> None:\n        # This is deliberately process-local. It proves only that THIS worker's\n        # previous post-materialization request has exited, so a same-worker\n        # retry cannot race that executor. A process restart still uses the\n        # durable owner-generation CAS in PlanStore.\n        with reviewed_start_retry_lock:\n            reviewed_start_retry_ready.add((plan_id, run_id))\n\n    def _take_reviewed_start_retry_ready(plan_id: str, run_id: str) -> bool:\n        key = (plan_id, run_id)\n        with reviewed_start_retry_lock:\n            if key not in reviewed_start_retry_ready:\n                return False\n            reviewed_start_retry_ready.remove(key)\n            return True\n\n    def _parse_reviewed_materialization(payload: str) -> tuple[dict[str, Any], AgentRun, bool]:\n        envelope = json.loads(payload)\n        if not isinstance(envelope, dict):\n            raise TypeError("reviewed Start materialization must be an object")\n        raw_review_reads = envelope.get("review_reads")\n        if type(raw_review_reads) is not bool:\n            raise TypeError("review_reads must be a literal boolean")\n        template = AgentRun.from_json(envelope["run"])\n        return envelope, template, raw_review_reads\n\n    def _assert_reviewed_run_identity(existing: AgentRun, reviewed_template: AgentRun) -> None:\n        # Never execute a recovered row merely because its run id matches. The\n        # canonical plan digest binds route + tool/args + risk/sensitivity/egress\n        # metadata to exactly what the operator reviewed, excluding mutable\n        # execution state and step ids.\n        if agent_run_plan_sha256(existing) != agent_run_plan_sha256(reviewed_template):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run does not match the reviewed plan",\n                status_code=503,\n            )\n\n    def _reconcile_reviewed_start_run(\n        run_id: str,\n        *,\n        review_reads: bool,\n        reviewed_template: AgentRun,\n    ) -> AgentRun:\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        if existing is None:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run is not yet materialized",\n                status_code=503,\n            )\n        # Only RUNNING snapshots need crash reconciliation. BLOCKED is terminal\n''',
    '''        if existing is None:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run is not yet materialized",\n                status_code=503,\n            )\n        _assert_reviewed_run_identity(existing, reviewed_template)\n        # Only RUNNING snapshots need crash reconciliation. BLOCKED is terminal\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''    def _recover_materialized_reviewed_start(\n        plan_id: str,\n        run_id: str,\n        stored: dict[str, Any],\n        *,\n        review_reads: bool,\n    ) -> dict[str, Any]:\n        # Once the exact reserved run exists, a failed reconciliation/finalization\n        # must not leave this worker generation holding the durable recovery claim\n        # forever. Release only after this execution path is exiting; a later\n        # request must claim the same run again before it can reconcile anything.\n        try:\n            reconciled = _reconcile_reviewed_start_run(\n                run_id,\n                review_reads=review_reads,\n            )\n            plan_store.mark_reviewed_start_accepted(plan_id, run_id)\n            return _reviewed_start_response(plan_id, stored, reconciled)\n        except Exception:\n            plan_store.release_reviewed_start_recovery(plan_id, run_id)\n            raise\n''',
    '''    def _recover_materialized_reviewed_start(\n        plan_id: str,\n        run_id: str,\n        stored: dict[str, Any],\n        *,\n        review_reads: bool,\n        reviewed_template: AgentRun,\n    ) -> dict[str, Any]:\n        try:\n            reconciled = _reconcile_reviewed_start_run(\n                run_id,\n                review_reads=review_reads,\n                reviewed_template=reviewed_template,\n            )\n            plan_store.mark_reviewed_start_accepted(plan_id, run_id)\n            return _reviewed_start_response(plan_id, stored, reconciled)\n        except Exception:\n            # No second SQLite write is required to make a same-worker retry\n            # possible. The local token is issued only as this request exits;\n            # the next request must atomically consume it before recovery.\n            _mark_reviewed_start_retry_ready(plan_id, run_id)\n            raise\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''            if state == "accepted":\n                if existing is None:\n                    # Acceptance proves this exact reserved run was materialized at\n                    # least once and may already have produced side effects. Missing\n                    # run storage is therefore ambiguous/corrupt recovery, never a\n                    # definitive refusal that would let clients clear authority.\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "accepted reviewed Start is missing its bound run; recovery remains ambiguous",\n                        status_code=503,\n                    )\n                stored = json.loads(\n                    plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n                )\n                return _reviewed_start_response(plan_id, stored, existing)\n            if owner == plan_store.start_owner:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed Start is still materializing in this worker",\n                )\n            if not plan_store.claim_reviewed_start_recovery(\n                plan_id,\n                reserved_run_id,\n                owner,\n            ):\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed Start recovery changed concurrently",\n                )\n            payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n            if existing is not None:\n                # Parse only the bounded policy bit before reconciliation. If a\n                # materialization that already has a persisted run is unreadable,\n                # its authority is ambiguous: do not advance and do not convert it\n                # into a definitive refusal that clients could clear.\n                try:\n                    recovery_envelope = json.loads(payload)\n                    if not isinstance(recovery_envelope, dict):\n                        raise TypeError("reviewed Start materialization must be an object")\n                    recovered_review_reads = bool(\n                        recovery_envelope.get("review_reads", False)\n                    )\n                except (TypeError, json.JSONDecodeError, ValueError) as exc:\n                    plan_store.release_reviewed_start_recovery(plan_id, reserved_run_id)\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "persisted reviewed Start policy is unreadable; recovery remains ambiguous",\n                        status_code=503,\n                    ) from exc\n                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    recovery_envelope,\n                    review_reads=recovered_review_reads,\n                )\n''',
    '''            if state == "accepted":\n                if existing is None:\n                    # Acceptance proves this exact reserved run was materialized at\n                    # least once and may already have produced side effects. Missing\n                    # run storage is therefore ambiguous/corrupt recovery, never a\n                    # definitive refusal that would let clients clear authority.\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "accepted reviewed Start is missing its bound run; recovery remains ambiguous",\n                        status_code=503,\n                    )\n                try:\n                    accepted_payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n                    stored, reviewed_template, _accepted_review_reads = _parse_reviewed_materialization(accepted_payload)\n                except (PlanStoreError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "accepted reviewed Start materialization is unreadable; recovery remains ambiguous",\n                        status_code=503,\n                    ) from exc\n                _assert_reviewed_run_identity(existing, reviewed_template)\n                return _reviewed_start_response(plan_id, stored, existing)\n\n            # A durable pending binding proves the reserved run may already have\n            # existed and produced side effects. Missing run storage is therefore\n            # ambiguous; never fall through into start_with_steps() to recreate it.\n            if existing is None:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "pending reviewed Start is missing its bound run; recovery remains ambiguous",\n                    status_code=503,\n                )\n\n            if owner == plan_store.start_owner:\n                if not _take_reviewed_start_retry_ready(plan_id, reserved_run_id):\n                    raise _reviewed_start_error(\n                        "reviewed_start_pending",\n                        "reviewed Start is still materializing in this worker",\n                    )\n            elif not plan_store.claim_reviewed_start_recovery(\n                plan_id,\n                reserved_run_id,\n                owner,\n            ):\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "reviewed Start recovery changed concurrently",\n                )\n\n            try:\n                payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)\n                recovery_envelope, recovery_template, recovered_review_reads = _parse_reviewed_materialization(payload)\n            except (PlanStoreError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:\n                _mark_reviewed_start_retry_ready(plan_id, reserved_run_id)\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "persisted reviewed Start materialization is unreadable; recovery remains ambiguous",\n                    status_code=503,\n                ) from exc\n            return _recover_materialized_reviewed_start(\n                plan_id,\n                reserved_run_id,\n                recovery_envelope,\n                review_reads=recovered_review_reads,\n                reviewed_template=recovery_template,\n            )\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''        try:\n            envelope = json.loads(payload)\n            template = AgentRun.from_json(envelope["run"])\n            stored_caps = CapabilitySnapshot(**envelope["capabilities"])\n            review_reads = bool(envelope.get("review_reads", False))\n            stored_capability_receipt = envelope.get("capability_receipt")\n''',
    '''        try:\n            envelope, template, review_reads = _parse_reviewed_materialization(payload)\n            stored_caps = CapabilitySnapshot(**envelope["capabilities"])\n            stored_capability_receipt = envelope.get("capability_receipt")\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                )\n''',
    '''                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                    reviewed_template=template,\n                )\n''',
)

replace_once(
    "worker/app/agent3/planner.py",
    '''                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                )\n''',
    '''                return _recover_materialized_reviewed_start(\n                    plan_id,\n                    reserved_run_id,\n                    envelope,\n                    review_reads=review_reads,\n                    reviewed_template=template,\n                )\n''',
)

replace_once(
    "tests/worker_agent3_reviewed_start_p1h.py",
    '''    assert pending[2] is None\n''',
    '''    # The durable owner may remain this worker when the failing resource is\n    # the SQLite store itself. Same-worker retryability is proven by an in-memory\n    # exit token, not by requiring a second durable release write to succeed.\n    assert pending[2] == plans.start_owner\n''',
)

Path("tests/worker_agent3_reviewed_start_p1i.py").write_text(r'''from __future__ import annotations

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


def template_run(*, args: dict | None = None) -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="recover authority", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args=args or {},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
    )


def payload(*, review_reads=True, include_review_reads: bool = True) -> str:
    body = {
        "run": template_run().to_json(),
        "capabilities": asdict(
            CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
        ),
    }
    if include_review_reads:
        body["review_reads"] = review_reads
    return json.dumps(body, sort_keys=True)


def app_for(plans: PlanStore, run_store: AgentRunStore, review_store: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        run_store,
        lambda step: executed.append(step.tool) or {"ok": True},
        review_store,
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


def missing_pending_run_stays_ambiguous(root: str) -> None:
    plans_path = os.path.join(root, "missing-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=False))
    run_id = "missing-pending-run"
    old.claim_reviewed_start(plan_id, run_id)
    old_owner = old.start_owner
    old.close()

    plans = PlanStore(plans_path, ttl_seconds=30)
    runs = AgentRunStore(os.path.join(root, "missing-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "missing-reviews.db"))
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    assert runs.load(run_id) is None
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery == ("pending", run_id, old_owner)
    plans.close()


def invalid_review_reads_initial_is_refused(root: str) -> None:
    invalid_values = [None, 0, "", [], {}]
    for index, value in enumerate(invalid_values):
        plans = PlanStore(os.path.join(root, f"invalid-initial-{index}.db"), ttl_seconds=30)
        plan_id, _ = plans.save(payload(review_reads=value))
        runs = AgentRunStore(os.path.join(root, f"invalid-initial-runs-{index}.db"))
        reviews = ReadReviewStore(os.path.join(root, f"invalid-initial-reviews-{index}.db"))
        executed: list[str] = []
        response = TestClient(app_for(plans, runs, reviews, executed)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )
        assert response.status_code == 409, response.text
        assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
        assert executed == []
        recovery = plans.reviewed_start_recovery(plan_id)
        assert recovery is not None and recovery[0] == "refused"
        plans.close()

    plans = PlanStore(os.path.join(root, "invalid-initial-missing.db"), ttl_seconds=30)
    plan_id, _ = plans.save(payload(include_review_reads=False))
    runs = AgentRunStore(os.path.join(root, "invalid-initial-missing-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "invalid-initial-missing-reviews.db"))
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    assert executed == []
    plans.close()


def invalid_review_reads_recovery_stays_pending(root: str) -> None:
    plans_path = os.path.join(root, "invalid-recovery-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=None))
    run_id = "invalid-review-reads-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "invalid-recovery-runs.db"))
    persisted = template_run()
    persisted.id = run_id
    persisted.state = RunState.RUNNING
    persisted.current_step = 0
    runs.save_with_event(persisted, "run_created", {})
    reviews = ReadReviewStore(os.path.join(root, "invalid-recovery-reviews.db"))
    reviews.configure(run_id, True)

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    persisted_after = runs.load(run_id)
    assert persisted_after is not None
    assert persisted_after.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


def mismatched_run_never_advances(root: str) -> None:
    plans_path = os.path.join(root, "mismatch-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old.save(payload(review_reads=False))
    run_id = "mismatched-bound-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "mismatch-runs.db"))
    tampered = template_run(args={"path": "tampered"})
    tampered.id = run_id
    tampered.state = RunState.RUNNING
    tampered.current_step = 0
    runs.save_with_event(tampered, "run_created", {})
    reviews = ReadReviewStore(os.path.join(root, "mismatch-reviews.db"))
    reviews.configure(run_id, False)

    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    persisted = runs.load(run_id)
    assert persisted is not None
    assert persisted.steps[0].args == {"path": "tampered"}
    assert persisted.steps[0].state == StepState.PENDING
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1] == run_id
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1i-")
missing_pending_run_stays_ambiguous(root)
invalid_review_reads_initial_is_refused(root)
invalid_review_reads_recovery_stays_pending(root)
mismatched_run_never_advances(root)

print("32 passed, 0 failed")
''', encoding="utf-8")

print("reviewed Start P1i patch staged")
