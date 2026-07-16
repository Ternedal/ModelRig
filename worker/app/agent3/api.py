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
    AgentStep,
    CapabilitySnapshot,
    ConfirmationError,
    RouteKind,
    RunConflict,
    TurnRequest,
)
from .integration import Agent3PlanError, PlannedToolCall, V2ToolAdapter
from .replan_runtime import (
    PersistentReadReplanner,
    ReplanJournal,
    ReplanJournalError,
)
from .replanner import ReadSuffixReplanner, ReplanError
from .routing import StrictTurnRouter
from .validation_gate import evaluate_configured_report


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


class ReplanReq(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    # Empty is valid: it means the remaining pending read window is unnecessary.
    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)


class CancelReq(BaseModel):
    reason: str | None = None


def _run_payload(run: AgentRun) -> dict[str, Any]:
    data = json.loads(run.to_json())
    # Confirmation digests are intentionally returned: the client must echo the
    # digest it showed. Results/args remain visible because this API is protected
    # by the backend or loopback-only when called directly.
    return data


def _clone_steps(run: AgentRun) -> list[AgentStep]:
    """Clone the validated original plan with fresh step IDs and no old results."""
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


ValidationProvider = Callable[[], dict[str, Any]]


def build_router(
    orchestrator: Agent3Orchestrator,
    adapter: V2ToolAdapter,
    capability_provider: Callable[[StartReq, V2ToolAdapter], CapabilitySnapshot] = _default_caps,
    validation_provider: ValidationProvider | None = None,
    worker_version: str | None = None,
    replan_service: PersistentReadReplanner | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3"])
    orchestrator.router = StrictTurnRouter()
    validation_provider = validation_provider or (
        lambda: evaluate_configured_report(current_version=worker_version)
    )

    def recover_or_block(run_id: str) -> list[dict[str, Any]]:
        """Resolve any write-ahead replan before the run may move again."""
        if replan_service is None:
            return []
        try:
            outcomes = replan_service.recover(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        conflicts = replan_service.journal.conflicts(run_id)
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail="run has an unresolved replan recovery conflict",
            )
        return outcomes

    @router.get("/status")
    def status() -> dict[str, Any]:
        validation = validation_provider()
        return {
            "enabled": True,
            "experimental": True,
            "planner": "explicit-plan-only",
            "replanner": (
                "explicit-pending-read-window" if replan_service is not None else "disabled"
            ),
            "production_tools_path_untouched": True,
            "max_steps": orchestrator.max_steps,
            "worker_version": worker_version,
            "rig_validation": validation,
            # Promotion evidence is advisory in this draft. Even a valid report
            # cannot activate production routing or tool execution by itself.
            "production_activation": False,
        }

    @router.post("/runs")
    def start(req: StartReq) -> dict[str, Any]:
        caps = capability_provider(req, adapter)

        if req.retry_of_run_id:
            original = orchestrator.store.load(req.retry_of_run_id)
            if original is None:
                raise HTTPException(status_code=404, detail="original run not found")
            # Retry semantics are server-owned: ignore mutable current UI state and
            # client plan fields. Reuse the stored message, route flags and plan.
            request = TurnRequest(
                message=original.request.message,
                mode=original.request.mode,
                tools=original.request.tools,
                rag=original.request.rag,
                has_image=original.request.has_image,
                voice=original.request.voice,
                allow_rag_cloud=original.request.allow_rag_cloud,
                auto_cloud_fallback=original.request.auto_cloud_fallback,
                retry_of_run_id=original.id,
                original_route=original.route.kind,
                conversation_id=original.request.conversation_id,
            )
            run = orchestrator.start_with_steps(
                request,
                caps,
                _clone_steps(original),
                proactive=original.proactive,
                allow_private_cloud=original.allow_private_cloud,
            )
            return {"run": _run_payload(run)}

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
            conversation_id=req.conversation_id,
        )
        route = orchestrator.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            run = orchestrator.start_with_steps(
                request,
                caps,
                [],
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
            )
            return {"run": _run_payload(run)}
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
        recovery = recover_or_block(run_id)
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": _run_payload(run), "replan_recovery": recovery}

    @router.get("/runs/{run_id}/events")
    def get_events(run_id: str, limit: int = 200) -> dict[str, Any]:
        if orchestrator.store.load(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"events": orchestrator.store.events(run_id, limit)}

    @router.get("/runs/{run_id}/replans")
    def get_replans(run_id: str) -> dict[str, Any]:
        if replan_service is None:
            raise HTTPException(status_code=501, detail="replanner is not mounted")
        recovery = recover_or_block(run_id)
        if orchestrator.store.load(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        revision, replan_count = replan_service.journal.revision_state(run_id)
        return {
            "revision": revision,
            "replan_count": replan_count,
            "transactions": replan_service.journal.history(run_id),
            "replan_recovery": recovery,
        }

    @router.post("/runs/{run_id}/replan")
    def replan(run_id: str, req: ReplanReq) -> dict[str, Any]:
        if replan_service is None:
            raise HTTPException(status_code=501, detail="replanner is not mounted")
        recover_or_block(run_id)
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            calls = [PlannedToolCall(step.tool, step.args) for step in req.plan]
            replacement_steps = adapter.build_steps(
                calls,
                run.route,
                run.request.conversation_id,
            )
            revised, receipt = replan_service.apply(
                run_id,
                replacement_steps,
                reason=req.reason,
            )
        except Agent3PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ReplanError, ReplanJournalError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": _run_payload(revised), "replan": receipt.to_dict()}

    @router.post("/runs/{run_id}/confirm")
    def confirm(run_id: str, req: ConfirmReq) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.confirm(run_id, req.step_id, req.decision, req.digest)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": _run_payload(run)}

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.advance(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": _run_payload(run)}

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, _req: CancelReq | None = None) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {"run": _run_payload(run)}

    return router


def _bounded_env_int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < low or value > high:
        raise RuntimeError(f"{name} must be between {low} and {high}")
    return value


def build_default_runtime() -> tuple[Agent3Orchestrator, V2ToolAdapter]:
    from .. import paths as _paths

    adapter = V2ToolAdapter()
    db_path = _paths.resolve("./kaliv-agent3.db", env="KALIV_AGENT3_DB")
    store = AgentRunStore(db_path)
    orchestrator = Agent3Orchestrator(store=store, executor=adapter.execute)
    orchestrator.router = StrictTurnRouter()
    return orchestrator, adapter


def build_default_replanner(orchestrator: Agent3Orchestrator) -> PersistentReadReplanner:
    from .. import paths as _paths

    journal_path = _paths.resolve(
        "./kaliv-agent3-replans.db",
        env="KALIV_AGENT3_REPLAN_DB",
    )
    max_replans = _bounded_env_int("KALIV_AGENT3_MAX_REPLANS", 3, low=0, high=20)
    return PersistentReadReplanner(
        orchestrator.store,
        ReplanJournal(journal_path),
        ReadSuffixReplanner(
            max_steps=orchestrator.max_steps,
            max_replans=max_replans,
        ),
    )


def mount_agent3(app: FastAPI) -> bool:
    """Mount once, only when the explicit feature flag is enabled."""
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False
    if getattr(app.state, "agent3_mounted", False):
        return True
    orchestrator, adapter = build_default_runtime()
    replan_service = build_default_replanner(orchestrator)
    app.include_router(
        build_router(
            orchestrator,
            adapter,
            worker_version=getattr(app, "version", None),
            replan_service=replan_service,
        )
    )
    app.state.agent3_mounted = True
    app.state.agent3_orchestrator = orchestrator
    app.state.agent3_replanner = replan_service
    return True
