from pathlib import Path

core = Path("worker/app/agent3/core.py")
core_text = core.read_text(encoding="utf-8")

old = '''        self.max_steps = max(1, max_steps)\n        self.confirmation_ttl_seconds = max(5, confirmation_ttl_seconds)\n\n    def start(\n'''
new = '''        self.max_steps = max(1, max_steps)\n        self.confirmation_ttl_seconds = max(5, confirmation_ttl_seconds)\n        # Reviewed-Start acceptance and Cancel need a short authority fence of\n        # their own. Do not reuse execution locks: Cancel must never wait for\n        # tool I/O merely because Start publication is serialized.\n        self._run_publication_locks = tuple(threading.RLock() for _ in range(64))\n\n    def run_publication_guard(self, run_id: str):\n        return self._run_publication_locks[hash(run_id) % len(self._run_publication_locks)]\n\n    def start(\n'''
if old not in core_text:
    raise SystemExit("missing Agent3Orchestrator init anchor")
core_text = core_text.replace(old, new, 1)

old = '''    def cancel(self, run_id: str) -> AgentRun:\n        # Stop must linearize against the exact run snapshot it observed. A\n        # worker can advance a step between load() and persistence; an\n        # unconditional save would roll that newer truth back inside a stale\n        # CANCELLED payload. Retry from the newer snapshot when the CAS loses.\n        while True:\n            run = self._require(run_id)\n            if run.state in {\n                RunState.BLOCKED,\n                RunState.COMPLETED,\n                RunState.FAILED,\n                RunState.CANCELLED,\n            }:\n                return run\n            expected_state = run.state\n            expected_payload = run.to_json()\n            run.state = RunState.CANCELLED\n            run.error = "Cancelled by user"\n            if self.store.save_with_event_if_unchanged(\n                run,\n                expected_state=expected_state,\n                expected_payload=expected_payload,\n                kind="run_cancelled",\n                payload={},\n            ):\n                return run\n'''
new = '''    def cancel(self, run_id: str) -> AgentRun:\n        # Stop must linearize against the exact run snapshot it observed. A\n        # worker can advance a step between load() and persistence; an\n        # unconditional save would roll that newer truth back inside a stale\n        # CANCELLED payload. Retry from the newer snapshot when the CAS loses.\n        #\n        # The publication guard is intentionally held only around this short\n        # state transition. Reviewed Start takes the same guard while deciding\n        # accepted-vs-cancelled, giving those two cross-store publications one\n        # process-local order without ever making Cancel wait for tool I/O.\n        with self.run_publication_guard(run_id):\n            while True:\n                run = self._require(run_id)\n                if run.state in {\n                    RunState.BLOCKED,\n                    RunState.COMPLETED,\n                    RunState.FAILED,\n                    RunState.CANCELLED,\n                }:\n                    return run\n                expected_state = run.state\n                expected_payload = run.to_json()\n                run.state = RunState.CANCELLED\n                run.error = "Cancelled by user"\n                if self.store.save_with_event_if_unchanged(\n                    run,\n                    expected_state=expected_state,\n                    expected_payload=expected_payload,\n                    kind="run_cancelled",\n                    payload={},\n                ):\n                    return run\n'''
if old not in core_text:
    raise SystemExit("missing Agent3Orchestrator cancel anchor")
core_text = core_text.replace(old, new, 1)
core.write_text(core_text, encoding="utf-8")

planner = Path("worker/app/agent3/planner.py")
text = planner.read_text(encoding="utf-8")

old = '''    def _finalize_cancelled_reviewed_start(plan_id: str, run_id: str) -> None:\n        # Cancellation is definitive only after the same-run execution guard has\n        # let the Start/recovery path observe the terminal CANCELLED snapshot.\n        # At that point no executor from this path is still in flight. Remove any\n        # checkpoint left by a crash between the run cancellation commit and the\n        # read-review cleanup, then publish a definitive refusal so clients may\n        # clear their ambiguous Start authority without calling the cancellation\n        # a successful Start acceptance.\n        if reviewing:\n            orchestrator.review_store.clear_waiting_if_matches(run_id)\n        plan_store.mark_reviewed_start_refused(plan_id, run_id)\n\n    def _parse_reviewed_materialization(payload: str) -> tuple[dict[str, Any], AgentRun, bool]:\n'''
new = '''    def _finalize_cancelled_reviewed_start(plan_id: str, run_id: str) -> None:\n        # Cancellation is definitive only after the same-run execution guard has\n        # let the Start/recovery path observe the terminal CANCELLED snapshot.\n        # At that point no executor from this path is still in flight. Remove any\n        # checkpoint left by a crash between the run cancellation commit and the\n        # read-review cleanup, then publish a definitive refusal so clients may\n        # clear their ambiguous Start authority without calling the cancellation\n        # a successful Start acceptance.\n        if reviewing:\n            orchestrator.review_store.clear_waiting_if_matches(run_id)\n        plan_store.mark_reviewed_start_refused(plan_id, run_id)\n\n    def _publish_reviewed_start_acceptance(\n        plan_id: str,\n        run_id: str,\n        stored: dict[str, Any],\n    ) -> dict[str, Any]:\n        # Run cancellation and reviewed-Start acceptance live in different SQLite\n        # stores, so there is no shared DB transaction to order them. This short\n        # process-local guard is the linearization boundary: whichever side gets\n        # it first publishes its durable authority first. It is deliberately not\n        # the execution guard and is never held around tool I/O.\n        with orchestrator.run_publication_guard(run_id):\n            fresh = orchestrator.store.load(run_id)\n            if fresh is None:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "persisted reviewed Start run disappeared before publication",\n                    status_code=503,\n                )\n            if fresh.state is RunState.CANCELLED:\n                _finalize_cancelled_reviewed_start(plan_id, run_id)\n                raise _ReviewedStartCancelled()\n            plan_store.mark_reviewed_start_accepted(plan_id, run_id)\n            return _reviewed_start_response(plan_id, stored, fresh)\n\n    def _parse_reviewed_materialization(payload: str) -> tuple[dict[str, Any], AgentRun, bool]:\n'''
if old not in text:
    raise SystemExit("missing planner publication helper anchor")
text = text.replace(old, new, 1)

old = '''        if reconciled.state is RunState.CANCELLED:\n            try:\n                _finalize_cancelled_reviewed_start(plan_id, run_id)\n            except Exception:\n                _mark_reviewed_start_retry_ready(plan_id, run_id)\n                raise\n            raise _reviewed_start_error(\n                "reviewed_start_refused",\n                "reviewed Start was cancelled before publication",\n            )\n\n        try:\n            plan_store.mark_reviewed_start_accepted(plan_id, run_id)\n            return _reviewed_start_response(plan_id, stored, reconciled)\n        except Exception:\n            _mark_reviewed_start_retry_ready(plan_id, run_id)\n            raise\n'''
new = '''        try:\n            return _publish_reviewed_start_acceptance(plan_id, run_id, stored)\n        except _ReviewedStartCancelled:\n            raise _reviewed_start_error(\n                "reviewed_start_refused",\n                "reviewed Start was cancelled before publication",\n            )\n        except Exception:\n            _mark_reviewed_start_retry_ready(plan_id, run_id)\n            raise\n'''
if old not in text:
    raise SystemExit("missing recovery acceptance block")
text = text.replace(old, new, 1)

old = '''                if existing.state is RunState.RUNNING:\n                    _assert_reviewed_run_identity(existing, reviewed_template)\n                return _reviewed_start_response(plan_id, stored, existing)\n'''
new = '''                if existing.state is RunState.RUNNING:\n                    _assert_reviewed_run_identity(existing, reviewed_template)\n                if existing.state is RunState.CANCELLED and reviewing:\n                    try:\n                        # Acceptance already linearized before this later Cancel.\n                        # A crash/failure in Cancel's secondary review-store cleanup\n                        # must not leave terminal cancellation carrying a waiting\n                        # human checkpoint that makes client recovery undecodable.\n                        orchestrator.review_store.clear_waiting_if_matches(reserved_run_id)\n                    except Exception as exc:\n                        raise _reviewed_start_error(\n                            "reviewed_start_pending",\n                            "accepted cancelled Start still has unresolved read-review authority",\n                            status_code=503,\n                        ) from exc\n                return _reviewed_start_response(plan_id, stored, existing)\n'''
if old not in text:
    raise SystemExit("missing accepted recovery block")
text = text.replace(old, new, 1)

old = '''            if run.id != reserved_run_id:\n                raise RuntimeError("reviewed Start materialized a different run id")\n            if run.state is RunState.CANCELLED:\n                raise _ReviewedStartCancelled()\n            plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)\n            return _reviewed_start_response(plan_id, envelope, run)\n'''
new = '''            if run.id != reserved_run_id:\n                raise RuntimeError("reviewed Start materialized a different run id")\n            return _publish_reviewed_start_acceptance(\n                plan_id, reserved_run_id, envelope\n            )\n'''
if old not in text:
    raise SystemExit("missing initial acceptance block")
text = text.replace(old, new, 1)
planner.write_text(text, encoding="utf-8")

p1m = Path("tests/worker_agent3_reviewed_start_p1m.py")
if p1m.exists():
    raise SystemExit("P1m regression already exists")
p1m.write_text(r'''from __future__ import annotations

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


def template_run(*, read: bool = False) -> AgentRun:
    step = AgentStep(
        tool="read_one" if read else "write_one",
        args={},
        risk=RiskClass.READ if read else RiskClass.WRITE,
        idempotent=read,
        summary="read one" if read else "write one",
    )
    return AgentRun(
        request=TurnRequest(message="publication race", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[step],
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


def build_app(orchestrator: ReviewingAgent3Orchestrator, plans: PlanStore) -> FastAPI:
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


def pause_start_before_publication(orchestrator: ReviewingAgent3Orchestrator):
    entered = threading.Event()
    release = threading.Event()
    original = orchestrator.run_publication_guard

    def wrapped(run_id: str):
        if threading.current_thread().name.startswith("start-publication"):
            entered.set()
            assert release.wait(5), "Start publication release timed out"
        return original(run_id)

    orchestrator.run_publication_guard = wrapped  # type: ignore[method-assign]
    return entered, release


def assert_refused(response, plans: PlanStore, plan_id: str, runs: AgentRunStore, run_id: str) -> None:
    assert response.status_code == 409, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_refused"
    assert plans.reviewed_start_recovery(plan_id) == ("refused", None, None)
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED


def initial_cancel_before_publication_wins(root: str) -> None:
    plans = PlanStore(os.path.join(root, "initial-plans.db"), ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = plans.save(materialization(reviewed))
    runs = AgentRunStore(os.path.join(root, "initial-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "initial-reviews.db"))
    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)
    entered, release = pause_start_before_publication(orchestrator)
    result: dict[str, object] = {}

    def start() -> None:
        result["response"] = TestClient(build_app(orchestrator, plans)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    thread = threading.Thread(target=start, name="start-publication-initial", daemon=True)
    thread.start()
    assert entered.wait(5), "initial Start never reached publication boundary"
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[0] == "pending" and recovery[1]
    run_id = recovery[1]
    waiting = runs.load(run_id)
    assert waiting is not None and waiting.state is RunState.WAITING_CONFIRMATION

    cancelled = orchestrator.cancel(run_id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert_refused(result["response"], plans, plan_id, runs, run_id)
    plans.close()


def recovery_cancel_before_publication_wins(root: str) -> None:
    plans_path = os.path.join(root, "recovery-plans.db")
    old = PlanStore(plans_path, ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = old.save(materialization(reviewed))
    run_id = "recovery-publication-run"
    old.claim_reviewed_start(plan_id, run_id)
    old.close()

    runs = AgentRunStore(os.path.join(root, "recovery-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "recovery-reviews.db"))
    reviews.configure(run_id, False)
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.WAITING_CONFIRMATION
    persisted.steps[0].state = StepState.WAITING_CONFIRMATION
    runs.save_with_event(persisted, "confirmation_required", {"step_id": persisted.steps[0].id})

    plans = PlanStore(plans_path, ttl_seconds=30)
    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)
    entered, release = pause_start_before_publication(orchestrator)
    result: dict[str, object] = {}

    def recover() -> None:
        result["response"] = TestClient(build_app(orchestrator, plans)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    thread = threading.Thread(target=recover, name="start-publication-recovery", daemon=True)
    thread.start()
    assert entered.wait(5), "recovery never reached publication boundary"
    cancelled = orchestrator.cancel(run_id)
    assert cancelled.state is RunState.CANCELLED
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert_refused(result["response"], plans, plan_id, runs, run_id)
    plans.close()


def acceptance_first_then_cancel_is_legitimate(root: str) -> None:
    plans = PlanStore(os.path.join(root, "accept-first-plans.db"), ttl_seconds=30)
    reviewed = template_run()
    plan_id, _ = plans.save(materialization(reviewed))
    runs = AgentRunStore(os.path.join(root, "accept-first-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "accept-first-reviews.db"))
    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)

    entered = threading.Event()
    release = threading.Event()
    original_mark = plans.mark_reviewed_start_accepted

    def delayed_mark(pid: str, rid: str) -> None:
        entered.set()
        assert release.wait(5), "acceptance release timed out"
        original_mark(pid, rid)

    plans.mark_reviewed_start_accepted = delayed_mark  # type: ignore[method-assign]
    result: dict[str, object] = {}

    def start() -> None:
        result["response"] = TestClient(build_app(orchestrator, plans)).post(
            f"/experimental/agent3/plans/{plan_id}/start"
        )

    start_thread = threading.Thread(target=start, name="acceptance-first-start", daemon=True)
    start_thread.start()
    assert entered.wait(5), "Start never entered acceptance write"
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery is not None and recovery[1]
    run_id = recovery[1]

    cancel_result: dict[str, AgentRun] = {}

    def cancel() -> None:
        cancel_result["run"] = orchestrator.cancel(run_id)

    cancel_thread = threading.Thread(target=cancel, name="acceptance-first-cancel", daemon=True)
    cancel_thread.start()
    cancel_thread.join(0.15)
    assert cancel_thread.is_alive(), "Cancel bypassed Start publication guard"
    release.set()
    start_thread.join(5)
    cancel_thread.join(5)
    assert not start_thread.is_alive() and not cancel_thread.is_alive()

    response = result["response"]
    assert response.status_code == 200, response.text
    accepted = plans.reviewed_start_recovery(plan_id)
    assert accepted is not None and accepted[0] == "accepted" and accepted[1] == run_id
    assert cancel_result["run"].state is RunState.CANCELLED
    final = runs.load(run_id)
    assert final is not None and final.state is RunState.CANCELLED
    plans.close()


def accepted_cancelled_recovery_clears_stale_checkpoint(root: str) -> None:
    plans = PlanStore(os.path.join(root, "accepted-cancelled-plans.db"), ttl_seconds=30)
    reviewed = template_run(read=True)
    plan_id, _ = plans.save(materialization(reviewed, review_reads=True))
    run_id = "accepted-cancelled-run"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.mark_reviewed_start_accepted(plan_id, run_id)

    runs = AgentRunStore(os.path.join(root, "accepted-cancelled-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "accepted-cancelled-reviews.db"))
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.CANCELLED
    persisted.error = "Cancelled by user"
    reviews.configure(run_id, True)
    reviews.set_waiting(
        run_id,
        completed_step_id=persisted.steps[0].id,
        completed_tool=persisted.steps[0].tool,
        window_start=0,
        window_end=1,
        removable_step_ids=[persisted.steps[0].id],
    )
    runs.save_with_event(persisted, "run_cancelled", {})

    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)
    response = TestClient(build_app(orchestrator, plans)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["state"] == "cancelled", body
    assert body["read_review"]["waiting"] is False, body
    assert reviews.get(run_id)["waiting"] is False
    accepted = plans.reviewed_start_recovery(plan_id)
    assert accepted is not None and accepted[0] == "accepted" and accepted[1] == run_id
    plans.close()


def accepted_cancelled_cleanup_failure_stays_pending(root: str) -> None:
    plans = PlanStore(os.path.join(root, "cleanup-failure-plans.db"), ttl_seconds=30)
    reviewed = template_run(read=True)
    plan_id, _ = plans.save(materialization(reviewed, review_reads=True))
    run_id = "cleanup-failure-run"
    plans.claim_reviewed_start(plan_id, run_id)
    plans.mark_reviewed_start_accepted(plan_id, run_id)

    runs = AgentRunStore(os.path.join(root, "cleanup-failure-runs.db"))
    reviews = ReadReviewStore(os.path.join(root, "cleanup-failure-reviews.db"))
    persisted = AgentRun.from_json(reviewed.to_json())
    persisted.id = run_id
    persisted.state = RunState.CANCELLED
    persisted.error = "Cancelled by user"
    reviews.configure(run_id, True)
    reviews.set_waiting(
        run_id,
        completed_step_id=persisted.steps[0].id,
        completed_tool=persisted.steps[0].tool,
        window_start=0,
        window_end=1,
        removable_step_ids=[persisted.steps[0].id],
    )
    runs.save_with_event(persisted, "run_cancelled", {})

    orchestrator = ReviewingAgent3Orchestrator(runs, lambda _: {"unexpected": True}, reviews)
    original_clear = reviews.clear_waiting_if_matches

    def fail_clear(*_args, **_kwargs):
        raise RuntimeError("simulated review-store outage")

    reviews.clear_waiting_if_matches = fail_clear  # type: ignore[method-assign]
    app = build_app(orchestrator, plans)
    response = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    accepted = plans.reviewed_start_recovery(plan_id)
    assert accepted is not None and accepted[0] == "accepted" and accepted[1] == run_id
    assert reviews.get(run_id)["waiting"] is True

    reviews.clear_waiting_if_matches = original_clear  # type: ignore[method-assign]
    retry = TestClient(app).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert retry.status_code == 200, retry.text
    assert retry.json()["read_review"]["waiting"] is False
    assert reviews.get(run_id)["waiting"] is False
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1m-")
initial_cancel_before_publication_wins(root)
recovery_cancel_before_publication_wins(root)
acceptance_first_then_cancel_is_legitimate(root)
accepted_cancelled_recovery_clears_stale_checkpoint(root)
accepted_cancelled_cleanup_failure_stays_pending(root)
print("P1m: reviewed-Start acceptance/cancellation publication races passed")
''', encoding="utf-8")

print("applied P1m acceptance/cancellation publication fix and regressions")
