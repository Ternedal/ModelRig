from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

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

    @router.post("/plans/{plan_id}/start")
    def start(plan_id: str) -> dict[str, Any]:
        _readiness, current_binding = _require_readiness(readiness_provider)
        try:
            envelope = json.loads(plan_store.consume(plan_id))
            if envelope.get("task_surface") != TASK_SURFACE:
                raise ValueError("wrong task surface")
            stored_binding = envelope["readiness_binding"]
            template = AgentRun.from_json(envelope["run"])
            stored_caps = CapabilitySnapshot(**envelope["capabilities"])
            stored_receipt = envelope.get("capability_receipt")
        except PlanStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="stored task plan is invalid") from exc

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
        run = orchestrator.start_with_steps(
            template.request,
            caps,
            [step.cloned_for_retry() for step in template.steps],
            proactive=False,
            allow_private_cloud=False,
        )
        # The normal task client has no confirmation route. This assertion catches
        # any future policy drift that turns a promoted read into a parked write.
        if run.state.value == "waiting_confirmation":
            orchestrator.cancel(run.id)
            raise HTTPException(
                status_code=500,
                detail="read-only task unexpectedly requested confirmation",
            )
        orchestrator.store.event(
            run.id,
            "task_surface_bound",
            {
                "surface": TASK_SURFACE,
                "readiness_binding": current_binding,
            },
        )
        response: dict[str, Any] = {
            "task_surface": TASK_SURFACE,
            "selected_surface": TASK_SURFACE,
            "fallback_surface": "agent2",
            "reason": TASK_REASON,
            "run": json.loads(run.to_json()),
            "events": orchestrator.store.events(run.id),
            "readiness_binding": current_binding,
            "production_activation": False,
            "normal_chat_route_unchanged": True,
        }
        if current_receipt is not None:
            response["capability_receipt"] = current_receipt
        return response

    return router
