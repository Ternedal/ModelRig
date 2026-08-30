from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from .. import ollama_client as _oc
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import capability_probe
from .capability_graph import CapabilityGraph
from .capability_receipt import agent_run_plan_sha256, evaluate_run_capabilities
from .core import (
    Agent3Orchestrator,
    AgentRun,
    CapabilitySnapshot,
    EgressClass,
    RiskClass,
    RouteKind,
    RunState,
    StepState,
    TurnRequest,
)
from .integration import Agent3PlanError, V2ToolAdapter
from .plan_store import PlanStore, PlanStoreError
from .planner import PlannerError, TypedPlanner
from .routing import StrictTurnRouter

TASK_SURFACE = "agent3_readonly"
TASK_REASON = "agent3_readonly_selected"
ReadinessProvider = Callable[[], dict[str, Any]]
CapabilityGraphProvider = Callable[[], CapabilityGraph]


class TaskExecutionPool:
    """Small, non-queuing executor for normal read-only task runs.

    A normal client must receive a run id before execution so Stop can target the
    rig rather than merely cancelling the phone's HTTP request. Capacity is
    deliberately bounded and non-queuing: when all workers are occupied, start
    fails before the single-use plan token is consumed.
    """

    def __init__(self, max_workers: int = 2) -> None:
        workers = max(1, min(int(max_workers), 8))
        self._slots = threading.BoundedSemaphore(workers)
        self._pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="kaliv-agent3-task",
        )

    def reserve(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release_reserved(self) -> None:
        self._slots.release()

    def submit_reserved(self, fn: Callable[..., Any], *args: Any) -> None:
        def run() -> None:
            try:
                fn(*args)
            finally:
                self._slots.release()

        # The caller owns the reservation until submit succeeds. If submit
        # raises, the caller's finally block releases it exactly once; after a
        # successful submit, the worker wrapper owns and releases it.
        self._pool.submit(run)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)


class TaskPlanReq(BaseModel):
    """The normal task surface deliberately owns almost no routing knobs.

    Cloud, RAG, memory, proactive mode, client plans and confirmation are absent
    rather than defaulted. The physical pilot proved one local read-only shape;
    a wider request schema would let a client ask for a shape that was never
    promoted.
    """

    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = None


def _readiness_binding(value: dict[str, Any]) -> dict[str, str]:
    pilot = value.get("pilot") if isinstance(value.get("pilot"), dict) else {}
    validation = (
        value.get("rig_validation")
        if isinstance(value.get("rig_validation"), dict)
        else {}
    )
    binding = {
        "pilot_report_sha256": pilot.get("report_sha256"),
        "pilot_candidate_git_sha": pilot.get("candidate_git_sha"),
        "rig_validation_report_sha256": validation.get("report_sha256"),
    }
    if not (
        isinstance(binding["pilot_report_sha256"], str)
        and len(binding["pilot_report_sha256"]) == 64
        and isinstance(binding["pilot_candidate_git_sha"], str)
        and len(binding["pilot_candidate_git_sha"]) == 40
        and isinstance(binding["rig_validation_report_sha256"], str)
        and len(binding["rig_validation_report_sha256"]) == 64
    ):
        raise HTTPException(
            status_code=409,
            detail="task readiness is missing exact evidence bindings",
        )
    return {name: str(item) for name, item in binding.items()}


def _require_readiness(provider: ReadinessProvider) -> tuple[dict[str, Any], dict[str, str]]:
    value = provider()
    if not isinstance(value, dict):
        raise HTTPException(status_code=409, detail="task readiness is unavailable")
    if value.get("production_activation") is not False:
        raise HTTPException(status_code=500, detail="task readiness claimed production activation")
    if value.get("normal_chat_route_unchanged") is not True:
        raise HTTPException(status_code=500, detail="task readiness claimed a normal-chat change")
    if not (
        value.get("selected_surface") == TASK_SURFACE
        and value.get("candidate_surface") == TASK_SURFACE
        and value.get("fallback_surface") == "agent2"
        and value.get("eligible_for_task_ui") is True
        and value.get("operator_enabled") is True
        and value.get("reason") == TASK_REASON
        and value.get("reasons") == []
    ):
        reason = value.get("reason") if isinstance(value.get("reason"), str) else "not_ready"
        raise HTTPException(
            status_code=409,
            detail={
                "selected_surface": value.get("selected_surface", "agent2"),
                "fallback_surface": "agent2",
                "reason": reason,
            },
        )
    return value, _readiness_binding(value)


def _assert_readonly_template(template: AgentRun) -> None:
    req = template.request
    route = template.route
    if not (
        req.mode == "rig"
        and req.tools is True
        and req.rag is False
        and req.allow_rag_cloud is False
        and req.auto_cloud_fallback is False
        and template.proactive is False
        and template.allow_private_cloud is False
        and route.kind == RouteKind.RIG_TOOLS_LOCAL
        and route.uses_rig is True
        and route.uses_tools is True
        and route.uses_cloud is False
        and route.uses_rag is False
    ):
        raise HTTPException(status_code=409, detail="task plan left the promoted read-only route")
    if any(
        step.risk != RiskClass.READ
        or step.egress != EgressClass.LOCAL
        or not step.idempotent
        for step in template.steps
    ):
        raise HTTPException(
            status_code=409,
            detail="task surface accepts only local idempotent read steps",
        )


def build_task_surface_router(
    adapter: V2ToolAdapter,
    orchestrator: Agent3Orchestrator,
    plan_store: PlanStore,
    readiness_provider: ReadinessProvider,
    execution_pool: TaskExecutionPool,
    *,
    planner: TypedPlanner | None = None,
    capability_graph_provider: CapabilityGraphProvider | None = None,
) -> APIRouter:
    """Build the normal, readiness-bound read-only task surface.

    This is intentionally separate from the developer planner API. A client can
    provide only a message and optional conversation id; the server authors the
    plan, binds it to exact physical evidence, permits only local idempotent reads
    and rechecks both readiness and capabilities before single-use start.
    """

    router = APIRouter(
        prefix="/experimental/agent3/task",
        tags=["experimental-agent3-task-surface"],
    )
    planner = planner or TypedPlanner(adapter)
    turn_router = StrictTurnRouter()

    def capability_receipt(template: AgentRun) -> dict[str, Any] | None:
        if capability_graph_provider is None:
            return None
        try:
            return evaluate_run_capabilities(
                capability_graph_provider(),
                template,
            ).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def task_context(run_id: str) -> tuple[AgentRun, dict[str, str], dict[str, Any] | None, list[dict[str, Any]]]:
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="task run not found")
        events = orchestrator.store.events(run_id)
        bound = next(
            (
                event.get("payload")
                for event in events
                if event.get("kind") == "task_surface_bound"
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("surface") == TASK_SURFACE
            ),
            None,
        )
        if not isinstance(bound, dict):
            # A normal task route must not become a read door into generic Agent 3
            # developer runs merely because somebody guessed an id.
            raise HTTPException(status_code=404, detail="task run not found")
        binding = bound.get("readiness_binding")
        if not isinstance(binding, dict):
            raise HTTPException(status_code=500, detail="task run lost its readiness binding")
        receipt = bound.get("capability_receipt")
        if receipt is not None and not isinstance(receipt, dict):
            raise HTTPException(status_code=500, detail="task run has an invalid capability receipt")
        _assert_readonly_template(run)
        return run, {str(k): str(v) for k, v in binding.items()}, receipt, events

    def task_response(run_id: str) -> dict[str, Any]:
        run, binding, receipt, events = task_context(run_id)
        if run.state == RunState.WAITING_CONFIRMATION:
            orchestrator.cancel(run.id)
            raise HTTPException(
                status_code=500,
                detail="read-only task unexpectedly requested confirmation",
            )
        response: dict[str, Any] = {
            "task_surface": TASK_SURFACE,
            "selected_surface": TASK_SURFACE,
            "fallback_surface": "agent2",
            "reason": TASK_REASON,
            "run": json.loads(run.to_json()),
            "events": events,
            "readiness_binding": binding,
            "terminal": run.state in {
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.CANCELLED,
                RunState.BLOCKED,
            },
            "production_activation": False,
            "normal_chat_route_unchanged": True,
        }
        if receipt is not None:
            response["capability_receipt"] = receipt
        return response

    def execute_task(run_id: str) -> None:
        """Advance only the promoted read path and stop immediately on cancel.

        The generic orchestrator also owns write confirmations and recovery. Its
        broad advance loop historically continued after `_execute()` had marked a
        late read as COMPLETED_AFTER_CANCEL, incremented the step and wrote a
        contradictory run_completed event. The normal task surface has a smaller
        authority, so its executor is smaller too: pending, local, idempotent reads
        only, with an explicit cancellation check before every step and before the
        terminal completion write.
        """
        try:
            run = orchestrator.store.load(run_id)
            if run is None or run.state in {
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.CANCELLED,
                RunState.BLOCKED,
            }:
                return
            _assert_readonly_template(run)

            while run.current_step < len(run.steps):
                fresh = orchestrator.store.load(run.id)
                if fresh is None or fresh.state == RunState.CANCELLED:
                    return
                step = run.steps[run.current_step]
                if step.state != StepState.PENDING:
                    raise RuntimeError("read-only task step left the pending state")

                decision = orchestrator.policy.evaluate(
                    step,
                    proactive=False,
                    allow_private_cloud=False,
                )
                orchestrator.store.event(
                    run.id,
                    "policy_decision",
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "action": decision.action,
                        "reason": decision.reason,
                    },
                )
                if decision.action != "execute":
                    step.state = StepState.BLOCKED
                    step.error = "Read-only task policy drifted outside execute"
                    run.state = RunState.BLOCKED
                    run.error = step.error
                    orchestrator.store.save_with_event(
                        run,
                        "task_surface_violation",
                        {
                            "step_id": step.id,
                            "tool": step.tool,
                            "action": decision.action,
                        },
                    )
                    return

                # Reuse the shared execution primitive for atomic step events and
                # COMPLETED_AFTER_CANCEL detection, but own the surrounding loop
                # so CANCELLED is terminal here rather than falling through.
                orchestrator._execute(run, step)
                if run.state in {RunState.FAILED, RunState.CANCELLED}:
                    return
                if step.state != StepState.SUCCEEDED:
                    raise RuntimeError("read-only task step did not finish successfully")
                run.current_step += 1
                run.state = RunState.RUNNING
                orchestrator.store.save(run)

            fresh = orchestrator.store.load(run.id)
            if fresh is None or fresh.state == RunState.CANCELLED:
                return
            run.state = RunState.COMPLETED
            run.answer = orchestrator.answerer(run)
            orchestrator.store.save_with_event(
                run,
                "run_completed",
                {"steps": len(run.steps)},
            )
        except Exception as exc:
            run = orchestrator.store.load(run_id)
            if run is not None and run.state not in {
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                run.state = RunState.FAILED
                run.error = f"Task execution failed: {exc}"
                orchestrator.store.save_with_event(
                    run,
                    "task_execution_failed",
                    {"error": str(exc)},
                )

    @router.post("/plan")
    async def preview(req: TaskPlanReq) -> dict[str, Any]:
        _readiness, binding = _require_readiness(readiness_provider)
        tools_ready = bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error)
        rig = capability_probe.measure()
        caps = CapabilitySnapshot(
            rig_reachable=rig["rig_reachable"],
            worker_ready=rig["worker_ready"],
            tools_ready=tools_ready,
            cloud_ready=False,
            rag_ready=False,
            voice_ready=False,
        )
        request = TurnRequest(
            message=req.message,
            mode="rig",
            tools=True,
            rag=False,
            allow_rag_cloud=False,
            auto_cloud_fallback=False,
            conversation_id=req.conversation_id,
        )
        route = turn_router.route(request, caps)
        if route.kind != RouteKind.RIG_TOOLS_LOCAL:
            raise HTTPException(status_code=409, detail=route.reason)

        try:
            proposal = await planner.plan(req.message)
            steps = adapter.build_steps(proposal.calls, route, req.conversation_id)
        except (PlannerError, Agent3PlanError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except _oc.OllamaError as exc:
            raise HTTPException(
                status_code=502, detail=f"planner model call failed: {exc}"
            ) from exc

        template = AgentRun(
            request=request,
            route=route,
            steps=steps,
            proactive=False,
            allow_private_cloud=False,
        )
        _assert_readonly_template(template)
        receipt = capability_receipt(template)

        plan_id: str | None = None
        expires_in_seconds: int | None = None
        if steps:
            envelope: dict[str, Any] = {
                "task_surface": TASK_SURFACE,
                "readiness_binding": binding,
                "run": template.to_json(),
                "capabilities": asdict(caps),
            }
            if receipt is not None:
                envelope["capability_receipt"] = receipt
            plan_id, expires_in_seconds = plan_store.save(
                json.dumps(envelope, ensure_ascii=False, sort_keys=True)
            )

        response: dict[str, Any] = {
            "task_surface": TASK_SURFACE,
            "selected_surface": TASK_SURFACE,
            "fallback_surface": "agent2",
            "reason": TASK_REASON,
            "route": {
                "kind": route.kind.value,
                "reason": route.reason,
                "uses_cloud": False,
                "uses_rig": True,
                "uses_tools": True,
                "uses_rag": False,
            },
            "rationale": proposal.rationale,
            "plan": [
                {
                    "tool": step.tool,
                    "args": step.args,
                    "risk": step.risk.value,
                    "sensitivity": step.sensitivity.value,
                    "egress": step.egress.value,
                    "idempotent": step.idempotent,
                    "summary": step.summary,
                }
                for step in steps
            ],
            "plan_id": plan_id,
            "expires_in_seconds": expires_in_seconds,
            "executed": False,
            "readiness_binding": binding,
            "production_activation": False,
            "normal_chat_route_unchanged": True,
        }
        if receipt is not None:
            response["capability_receipt"] = receipt
        return response

    @router.post("/plans/{plan_id}/start", status_code=202)
    def start(plan_id: str) -> dict[str, Any]:
        _readiness, current_binding = _require_readiness(readiness_provider)
        if not execution_pool.reserve():
            raise HTTPException(
                status_code=503,
                detail="all read-only task workers are busy; retry the same plan token",
            )
        reserved = True
        try:
            envelope = json.loads(plan_store.consume(plan_id))
            if envelope.get("task_surface") != TASK_SURFACE:
                raise ValueError("wrong task surface")
            stored_binding = envelope["readiness_binding"]
            template = AgentRun.from_json(envelope["run"])
            stored_caps = CapabilitySnapshot(**envelope["capabilities"])
            stored_receipt = envelope.get("capability_receipt")

            if stored_binding != current_binding:
                raise HTTPException(
                    status_code=409,
                    detail="task readiness evidence changed; preview the task again",
                )
            _assert_readonly_template(template)

            current_receipt: dict[str, Any] | None = None
            if stored_receipt is not None:
                if not isinstance(stored_receipt, dict):
                    raise HTTPException(status_code=409, detail="stored capability receipt is invalid")
                if capability_graph_provider is None:
                    raise HTTPException(
                        status_code=409,
                        detail="capability receipt validation is not mounted",
                    )
                if stored_receipt.get("plan_sha256") != agent_run_plan_sha256(template):
                    raise HTTPException(
                        status_code=409,
                        detail="stored capability receipt does not match the task plan",
                    )
                current_receipt = capability_receipt(template)
                if current_receipt != stored_receipt:
                    raise HTTPException(
                        status_code=409,
                        detail="capability receipt is stale; preview the task again",
                    )
                if not bool(current_receipt.get("allowed", False)):
                    raise HTTPException(
                        status_code=409,
                        detail="task plan is blocked by current capabilities",
                    )

            caps = CapabilitySnapshot(
                rig_reachable=stored_caps.rig_reachable,
                worker_ready=stored_caps.worker_ready,
                tools_ready=bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error),
                cloud_ready=False,
                rag_ready=False,
                voice_ready=False,
            )
            route = orchestrator.router.route(template.request, caps)
            run = AgentRun(
                request=template.request,
                route=route,
                steps=[step.cloned_for_retry() for step in template.steps],
                proactive=False,
                allow_private_cloud=False,
            )
            _assert_readonly_template(run)
            if len(run.steps) > orchestrator.max_steps:
                raise HTTPException(status_code=409, detail="task plan exceeds the execution limit")

            orchestrator.store.save_with_event(
                run,
                "run_created",
                {"route": route.kind.value, "steps": len(run.steps)},
            )
            bound_payload: dict[str, Any] = {
                "surface": TASK_SURFACE,
                "readiness_binding": current_binding,
            }
            if current_receipt is not None:
                bound_payload["capability_receipt"] = current_receipt
            orchestrator.store.event(run.id, "task_surface_bound", bound_payload)
            try:
                execution_pool.submit_reserved(execute_task, run.id)
            except Exception as exc:
                orchestrator.cancel(run.id)
                raise HTTPException(
                    status_code=503,
                    detail="read-only task executor is unavailable",
                ) from exc
            reserved = False
            return task_response(run.id)
        except PlanStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="stored task plan is invalid") from exc
        finally:
            if reserved:
                execution_pool.release_reserved()

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        # Outcome visibility remains available if readiness later falls back to
        # Agent 2. A running task must never disappear merely because its evidence
        # expired between start and poll.
        return task_response(run_id)

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str) -> dict[str, Any]:
        # Stop has the same rule as status: it must remain reachable after a
        # readiness/operator change. task_context prevents access to generic runs.
        task_context(run_id)
        orchestrator.cancel(run_id)
        return task_response(run_id)

    return router
