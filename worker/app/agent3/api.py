from __future__ import annotations

import json
import os
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    CapabilitySnapshot,
    ConfirmationError,
    RouteKind,
    RunConflict,
    TurnRequest,
)
from .integration import Agent3PlanError, PlannedToolCall, V2ToolAdapter


class PlanStepReq(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)


class StartReq(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    mode: str = Field(default="rig", pattern="^(rig|cloud)$")
    tools: bool = True
    rag: bool = False
    has_image: bool = False
    voice: bool = False
    allow_rag_cloud: bool = False
    allow_private_cloud: bool = False
    auto_cloud_fallback: bool = False
    cloud_ready: bool = False
    conversation_id: str | None = None
    retry_of_run_id: str | None = None
    original_route: RouteKind | None = None
    proactive: bool = False
    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)


class ConfirmReq(BaseModel):
    step_id: str
    decision: str = Field(pattern="^(approve|deny)$")
    digest: str


class CancelReq(BaseModel):
    reason: str | None = None


def _run_payload(run: AgentRun) -> dict[str, Any]:
    data = json.loads(run.to_json())
    # Confirmation digests are intentionally returned: the client must echo the
    # digest it showed. Results/args remain visible because this API is protected
    # by the backend or loopback-only when called directly.
    return data


def _default_caps(req: StartReq, adapter: V2ToolAdapter) -> CapabilitySnapshot:
    tools_ready = bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error)
    return CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=tools_ready,
        cloud_ready=req.cloud_ready,
        rag_ready=True,
        voice_ready=False,
    )


def build_router(
    orchestrator: Agent3Orchestrator,
    adapter: V2ToolAdapter,
    capability_provider: Callable[[StartReq, V2ToolAdapter], CapabilitySnapshot] = _default_caps,
) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return {
            "enabled": True,
            "experimental": True,
            "planner": "explicit-plan-only",
            "production_tools_path_untouched": True,
            "max_steps": orchestrator.max_steps,
        }

    @router.post("/runs")
    def start(req: StartReq) -> dict[str, Any]:
        if not req.plan:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Agent 3.0 draft currently requires an explicit validated plan; "
                    "LLM planning is deliberately not enabled yet"
                ),
            )
        if not req.tools:
            raise HTTPException(status_code=400, detail="an explicit tool plan requires tools=true")
        request = TurnRequest(
            message=req.message,
            mode=req.mode,
            tools=req.tools,
            rag=req.rag,
            has_image=req.has_image,
            voice=req.voice,
            allow_rag_cloud=req.allow_rag_cloud,
            auto_cloud_fallback=req.auto_cloud_fallback,
            retry_of_run_id=req.retry_of_run_id,
            original_route=req.original_route,
            conversation_id=req.conversation_id,
        )
        caps = capability_provider(req, adapter)
        route = orchestrator.router.route(request, caps)
        try:
            calls = [PlannedToolCall(step.tool, step.args) for step in req.plan]
            steps = adapter.build_steps(calls, route, req.conversation_id)
            run = orchestrator.start_with_steps(
                request,
                caps,
                steps,
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
            )
        except Agent3PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"run": _run_payload(run)}

    @router.get("/runs")
    def list_runs(limit: int = 50) -> dict[str, Any]:
        return {"runs": [_run_payload(run) for run in orchestrator.store.recent(limit)]}

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": _run_payload(run)}

    @router.get("/runs/{run_id}/events")
    def get_events(run_id: str, limit: int = 200) -> dict[str, Any]:
        if orchestrator.store.load(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"events": orchestrator.store.events(run_id, limit)}

    @router.post("/runs/{run_id}/confirm")
    def confirm(run_id: str, req: ConfirmReq) -> dict[str, Any]:
        try:
            run = orchestrator.confirm(run_id, req.step_id, req.decision, req.digest)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": _run_payload(run)}

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, Any]:
        try:
            run = orchestrator.advance(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": _run_payload(run)}

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, _req: CancelReq | None = None) -> dict[str, Any]:
        try:
            run = orchestrator.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {"run": _run_payload(run)}

    return router


def build_default_runtime() -> tuple[Agent3Orchestrator, V2ToolAdapter]:
    from .. import paths as _paths

    adapter = V2ToolAdapter()
    db_path = _paths.resolve("./kaliv-agent3.db", env="KALIV_AGENT3_DB")
    store = AgentRunStore(db_path)
    orchestrator = Agent3Orchestrator(store=store, executor=adapter.execute)
    return orchestrator, adapter


def mount_agent3(app: FastAPI) -> bool:
    """Mount once, only when the explicit feature flag is enabled."""
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False
    if getattr(app.state, "agent3_mounted", False):
        return True
    orchestrator, adapter = build_default_runtime()
    app.include_router(build_router(orchestrator, adapter))
    app.state.agent3_mounted = True
    app.state.agent3_orchestrator = orchestrator
    return True
