from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import ollama_client as oc
from .core import (
    Agent3Orchestrator,
    AgentRun,
    AgentStep,
    CapabilitySnapshot,
    RouteKind,
    TurnRequest,
)
from .integration import Agent3PlanError, PlannedToolCall, V2ToolAdapter
from .plan_store import PlanStore, PlanStoreError
from .routing import StrictTurnRouter


class PlannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlanProposal:
    calls: list[PlannedToolCall]
    rationale: str = ""


ChatFn = Callable[[list[dict], str | None], Awaitable[str]]


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else value


def _clone_steps(run: AgentRun) -> list[AgentStep]:
    return [
        AgentStep(
            tool=step.tool,
            args=dict(step.args),
            risk=step.risk,
            sensitivity=step.sensitivity,
            egress=step.egress,
            origin=step.origin,
            conversation_id=step.conversation_id,
            summary=step.summary,
        )
        for step in run.steps
    ]


class TypedPlanner:
    """Local, plan-only LLM adapter.

    The model may output only `{steps:[{tool,args}], rationale}`. Risk,
    sensitivity, confirmation and egress never appear in the model-owned schema.
    Unknown/disabled tools are rejected later by V2ToolAdapter.
    """

    def __init__(self, adapter: V2ToolAdapter, chat_fn: ChatFn | None = None, max_steps: int = 12):
        self.adapter = adapter
        self.chat_fn = chat_fn or self._chat
        self.max_steps = max(1, min(max_steps, 12))

    @staticmethod
    async def _chat(messages: list[dict], model: str | None) -> str:
        return await oc.chat(messages, model=model)

    async def plan(self, message: str, model: str | None = None) -> PlanProposal:
        catalog = self.adapter.tool_catalog()
        if not catalog:
            raise PlannerError("no tools are enabled")
        system = (
            "You are Kaliv's PLAN-ONLY component. Return ONLY one JSON object. "
            "Schema: {\"steps\":[{\"tool\":\"name\",\"args\":{}}],"
            "\"rationale\":\"short explanation\"}. Use only tools from the catalog. "
            "Do not include risk, approval, sensitivity, egress, status, shell commands, "
            "or prose outside JSON. If no tool is useful, return an empty steps array. "
            f"Maximum {self.max_steps} steps. Tool catalog: "
            + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
        )
        raw = await self.chat_fn(
            [{"role": "system", "content": system}, {"role": "user", "content": message}],
            model,
        )
        try:
            payload = json.loads(_strip_code_fence(raw))
        except (json.JSONDecodeError, TypeError) as exc:
            raise PlannerError("planner did not return valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) - {"steps", "rationale"}:
            raise PlannerError("planner response has unsupported top-level fields")
        steps = payload.get("steps")
        if not isinstance(steps, list):
            raise PlannerError("planner response must contain a steps array")
        if len(steps) > self.max_steps:
            raise PlannerError(f"planner returned more than {self.max_steps} steps")
        calls: list[PlannedToolCall] = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or set(step) != {"tool", "args"}:
                raise PlannerError(f"step {index + 1} must contain exactly tool and args")
            tool = step.get("tool")
            args = step.get("args")
            if not isinstance(tool, str) or not tool.strip():
                raise PlannerError(f"step {index + 1} has an invalid tool name")
            if not isinstance(args, dict):
                raise PlannerError(f"step {index + 1} args must be an object")
            calls.append(PlannedToolCall(tool.strip(), args))
        rationale = payload.get("rationale", "")
        if not isinstance(rationale, str):
            raise PlannerError("rationale must be a string")
        return PlanProposal(calls=calls, rationale=rationale[:1000])


class PlanPreviewReq(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    mode: str = Field(default="rig", pattern="^(rig|cloud)$")
    rag: bool = False
    allow_rag_cloud: bool = False
    allow_private_cloud: bool = False
    cloud_ready: bool = False
    conversation_id: str | None = None
    planner_model: str | None = None
    proactive: bool = False


def build_planner_router(
    adapter: V2ToolAdapter,
    planner: TypedPlanner | None = None,
    *,
    orchestrator: Agent3Orchestrator | None = None,
    plan_store: PlanStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3"])
    planner = planner or TypedPlanner(adapter)
    plan_store = plan_store or PlanStore(":memory:")
    turn_router = StrictTurnRouter()

    @router.post("/plan")
    async def preview(req: PlanPreviewReq) -> dict[str, Any]:
        tools_ready = bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error)
        caps = CapabilitySnapshot(
            rig_reachable=True,
            worker_ready=True,
            tools_ready=tools_ready,
            cloud_ready=req.cloud_ready,
            rag_ready=True,
        )
        request = TurnRequest(
            message=req.message,
            mode=req.mode,
            tools=True,
            rag=req.rag,
            allow_rag_cloud=req.allow_rag_cloud,
            conversation_id=req.conversation_id,
        )
        route = turn_router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            raise HTTPException(status_code=409, detail=route.reason)
        try:
            proposal = await planner.plan(req.message, req.planner_model)
            steps = adapter.build_steps(proposal.calls, route, req.conversation_id)
        except (PlannerError, Agent3PlanError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        plan_id: str | None = None
        expires_in_seconds: int | None = None
        if steps:
            template = AgentRun(
                request=request,
                route=route,
                steps=steps,
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
            )
            payload = json.dumps(
                {"run": template.to_json(), "capabilities": asdict(caps)},
                ensure_ascii=False,
                sort_keys=True,
            )
            plan_id, expires_in_seconds = plan_store.save(payload)

        return {
            "route": {
                "kind": route.kind.value,
                "reason": route.reason,
                "uses_cloud": route.uses_cloud,
                "uses_rig": route.uses_rig,
                "uses_tools": route.uses_tools,
                "uses_rag": route.uses_rag,
            },
            "rationale": proposal.rationale,
            "plan": [
                {
                    "tool": step.tool,
                    "args": step.args,
                    "risk": step.risk.value,
                    "sensitivity": step.sensitivity.value,
                    "egress": step.egress.value,
                    "summary": step.summary,
                }
                for step in steps
            ],
            "plan_id": plan_id,
            "expires_in_seconds": expires_in_seconds,
            "executed": False,
        }

    @router.post("/plans/{plan_id}/start")
    def start_reviewed_plan(plan_id: str) -> dict[str, Any]:
        if orchestrator is None:
            raise HTTPException(status_code=501, detail="plan execution is not mounted")
        try:
            envelope = json.loads(plan_store.consume(plan_id))
            template = AgentRun.from_json(envelope["run"])
            stored_caps = CapabilitySnapshot(**envelope["capabilities"])
        except PlanStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="stored plan is invalid") from exc

        # Recheck the gate at start time. A kill-switch decision made after the
        # preview wins over the earlier plan.
        caps = CapabilitySnapshot(
            rig_reachable=stored_caps.rig_reachable,
            worker_ready=stored_caps.worker_ready,
            tools_ready=bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error),
            cloud_ready=stored_caps.cloud_ready,
            rag_ready=stored_caps.rag_ready,
            voice_ready=stored_caps.voice_ready,
        )
        run = orchestrator.start_with_steps(
            template.request,
            caps,
            _clone_steps(template),
            proactive=template.proactive,
            allow_private_cloud=template.allow_private_cloud,
        )
        return {"run": json.loads(run.to_json()), "plan_id": plan_id}

    return router
